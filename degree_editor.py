"""Optional player nameplates, isolated from the character's identity.title."""
import copy
import re
from PIL import Image


def validate(project):
    rows = project.get('degrees', [])
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError('可佩戴铭牌必须为数组，最多 32 款')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', row['id']) or row['id'] in ids:
            raise ValueError('铭牌编号无效或重复')
        ids.add(row['id'])
        for key in ('asset', 'safeMaskAsset', 'frameAsset', 'letteringAsset'):
            aid = row.get(key)
            if aid and project.get('assets', {}).get(aid, {}).get('mime') != 'image/png':
                raise ValueError('铭牌引用的图片无效：' + key)
        for key in ('name', 'note', 'safeAreaEvidence'):
            if not isinstance(row.get(key, ''), str) or len(row.get(key, '')) > 4000:
                raise ValueError('铭牌说明必须为文本')
    return rows


def preview(store, project, row):
    from studio_core import image_from, png_bytes
    validate(project)
    if not row.get('asset'):
        raise ValueError('请先关联 320×50 RGBA 铭牌图')
    image = image_from(store.asset_bytes(project, row['asset']))
    if image.size != (320, 50):
        raise ValueError('铭牌画布必须为 320×50，当前为 %s×%s' % image.size)
    lettering = None
    if row.get('letteringAsset'):
        lettering = image_from(store.asset_bytes(project, row['letteringAsset']))
        if lettering.size != image.size:
            raise ValueError('完整文字层（文字、描边、阴影）必须为 320×50 RGBA')
    outside, whole_outside, lettering_pixels = None, None, None
    mask = None
    if row.get('safeMaskAsset'):
        mask = image_from(store.asset_bytes(project, row['safeMaskAsset']))
        if mask.size != image.size:
            raise ValueError('实际内框安全区遮罩必须为 320×50；Alpha>0 表示允许区域')
        def outside_pixels(layer):
            return sum(1 for alpha, safe in zip(layer.getchannel('A').tobytes(), mask.getchannel('A').tobytes()) if alpha > 0 and safe == 0)
        whole_outside = outside_pixels(image)
        outside = outside_pixels(lettering) if lettering is not None else whole_outside
    if lettering is not None:
        lettering_pixels = sum(1 for alpha in lettering.getchannel('A').tobytes() if alpha > 0)
    frame = None
    if row.get('frameAsset'):
        frame = image_from(store.asset_bytes(project, row['frameAsset']))
        if frame.size != image.size:
            raise ValueError('框层参考必须为 320×50')
    # Never silently clip artwork to fit; the frame overlay only helps inspection.
    composed = image.copy()
    if frame is not None:
        composed.alpha_composite(frame)
    half = composed.resize((160, 25), Image.Resampling.LANCZOS)
    evidence = row.get('safeAreaEvidence', '')
    status = ('needs_lettering_layer' if lettering is None else 'empty_lettering_layer' if not lettering_pixels
              else 'needs_review' if mask is None or not evidence.strip() else 'outside' if outside else 'inside_declared_mask')
    check_object = 'lettering_with_outline_and_shadow' if lettering is not None else 'whole_artwork_candidate'
    result = {'id': row['id'], 'size': [320, 50], 'halfSize': [160, 25], 'outsideSafePixels': outside,
              'safeAreaCheckObject': check_object, 'letteringAsset': row.get('letteringAsset'),
              'letteringOutsideSafePixels': outside if lettering is not None else None,
              'wholeArtworkCandidateOutsideSafePixels': whole_outside, 'letteringAlphaPositivePixels': lettering_pixels,
              'safeAreaEvidence': row.get('safeAreaEvidence', ''),
              'safeAreaStatus': status,
              'safeAreaMethod': '检查对象的每个Alpha>0像素对照同位置安全区遮罩；遮罩Alpha>0声明整个像素格允许',
              'safeAreaScope': '文字层应包含全部文字、描边、阴影；框和装饰不计作文字' if lettering is not None else '缺少完整文字分层，整图（含框/装饰）仅作候选检查，文字安全区未知',
              'letteringCompositionVerified': False, 'originalArtworkModified': False,
              'readability': 'needs_visual_review', 'nativeVerified': False, 'gameReady': False}
    return png_bytes(composed), png_bytes(half), result


def report(store, project):
    rows = []
    for row in validate(project):
        if not row.get('asset'):
            rows.append({'id': row['id'], 'name': row.get('name', ''), 'status': 'author_pending', 'nativeVerified': False})
            continue
        try:
            _, _, result = preview(store, project, row)
            result['name'] = row.get('name', '')
            rows.append(result)
        except ValueError as exc:
            rows.append({'id': row['id'], 'status': 'invalid', 'error': str(exc), 'nativeVerified': False})
    return {'schema': 'starpoint-degree-handoff-v1', 'degrees': rows, 'gameReady': False,
            'pending': ['当前合并数据分配游戏 ID、排序与奖励', '原生列表、资料页、佩戴和半尺寸可读性', '资格、事务、持有幂等及存档接入'] if rows else []}


def compile_files(store, project):
    from studio_core import image_from, png_bytes
    files = {}
    for row in validate(project):
        if not row.get('asset'):
            continue
        full, half, _ = preview(store, project, row)
        original = png_bytes(image_from(store.asset_bytes(project, row['asset'])))
        files['handoff/degrees/' + row['id'] + '.png'] = original
        files['handoff/degrees/' + row['id'] + '-frame-preview.png'] = full
        files['handoff/degrees/' + row['id'] + '-half-preview.png'] = half
        if row.get('letteringAsset'):
            files['handoff/degrees/' + row['id'] + '-lettering-complete.png'] = png_bytes(image_from(store.asset_bytes(project, row['letteringAsset'])))
    return files
