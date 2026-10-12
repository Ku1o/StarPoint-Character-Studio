"""Read-only playback of one byte-bound saved author reference.

Uses the editor's saved clips/native commands and its channel composer. It does
not compile a character, repair native rows, save a scene or simulate combat.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import math
import re

import author_reuse
from effect_channels import compose_frames, validate_channels
from studio_core import StudioError, image_from, integer, number

MAX_FRAMES = 4096
MAX_COMMANDS = 200000
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


def _finite(value, low=-1000000, high=1000000):
    return number(value, low, high, '参考显示参数')


def _command(command):
    if not isinstance(command, dict) or not isinstance(command.get('asset'), str):
        raise StudioError('参考图块缺少明确素材')
    matrix = command.get('matrix')
    if not isinstance(matrix, list) or len(matrix) != 6:
        raise StudioError('参考变换矩阵无效')
    for value in matrix:
        _finite(value)
    _finite(command.get('alpha', 1), 0, 1)
    for key in ('fx', 'fy'):
        _finite(command.get(key, 0))
    if 'colorTransform' in command:
        color = command['colorTransform']
        if not isinstance(color, list) or len(color) != 4:
            raise StudioError('参考颜色变换无效')
        for value in color:
            _finite(value)
    if 'color' in command:
        integer(command['color'], 0, 0xffffffff, '参考颜色')


def preview(store, project, choice, digest):
    """API contract: caller loads the current project under its store lock.

    A stale/missing digest or required corrupt asset is rejected. Incomplete
    DSL/summon semantics return pending with no fabricated frames or sound.
    All URLs contain the exact registered original media bytes.
    """
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise StudioError('请先检查参考身份，再打开预览')
    entries, _, _, input_issues = author_reuse._snapshot(store, project)
    selected = next((item for item in entries if item['id'] == choice), None)
    if selected is None or selected['identity']['sha256'] != digest:
        raise StudioError('参考输入或原对象已变化；请重新检查并选择')
    model = copy.deepcopy(selected['model'])
    result = {'name': selected['label'], 'referenceKind': selected['kind'],
              'mode': 'animation', 'kind': model.get('kind', 'once') if isinstance(model, dict) else 'once',
              'frames': [], 'assets': {}, 'audio': [], 'scale': 1,
              'runtimeSpeed': 1, 'issues': [str(issue.get('reason', '参考来源待核')) for issue in input_issues], 'sourceRevision': project['revision'],
              'identity': copy.deepcopy(selected['identity']), 'readonly': True,
              'gameReady': False, 'behaviorVerified': False, 'status': 'pending'}
    if selected['kind'] in ('skill', 'summon'):
        result['mode'] = 'pending'
        result['issues'] = ['此参考的目标、条件、召唤或战斗行为需要制作方核对。请先从动作、特效阶段和声音参考试看；这里没有模拟伤害或完整技能。']
        return result

    size = 0
    loaded = {}

    def asset(aid, kind):
        nonlocal size
        if aid in loaded:
            if loaded[aid]['kind'] != kind:
                raise StudioError('参考素材类型冲突')
            return loaded[aid]
        meta = project.get('assets', {}).get(aid)
        logical = selected['assets'].get(aid)
        raw = selected['local'].get(logical)
        if not isinstance(meta, dict) or raw is None:
            raise StudioError('参考缺少所需素材：' + str(aid))
        if meta.get('sha256') != hashlib.sha256(raw).hexdigest():
            raise StudioError('参考素材实际字节与登记 SHA 不一致')
        mime = meta.get('mime', '')
        if (kind == 'image' and mime != 'image/png') or (kind == 'audio' and mime not in ('audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/ogg')):
            raise StudioError('参考素材格式不支持')
        size += len(raw)
        if size > MAX_RESPONSE_BYTES:
            raise StudioError('参考预览媒体超出有界预算')
        item = {'url': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode(),
                'kind': kind, 'sha256': meta['sha256']}
        if kind == 'image':
            image = image_from(raw)
            item.update(width=image.width, height=image.height)
            result['assets'][aid] = item['url']
        loaded[aid] = item
        return item

    if selected['kind'] == 'sound':
        sound = asset(model.get('asset'), 'audio')
        result.update(mode='sound', kind='once', status='pending' if input_issues else 'media-ready')
        result['audio'] = [{'start': 0, 'end': -1, 'loop': 1, 'rate': 1,
                            'volume': 1, 'url': sound['url'], 'sha256': sound['sha256']}]
        return result

    if result['kind'] not in ('once', 'loop', 'pass', 'stop'):
        raise StudioError('参考播放方式无效')
    result['scale'] = number(model.get('frameScale', 1), .05, 20, '参考显示倍率')
    result['runtimeSpeed'] = number(model.get('runtimeSpeed', 1), .1, 4, '参考播放倍率')
    frames = []
    if model.get('native'):
        source = model.get('nativeFrames', [])
        if not isinstance(source, list) or not 1 <= len(source) <= MAX_FRAMES:
            raise StudioError('参考骨架帧无效或超限')
        total = 0
        for frame in source:
            if not isinstance(frame, list):
                raise StudioError('参考骨架帧无效')
            total += len(frame)
            if total > MAX_COMMANDS:
                raise StudioError('参考图块指令超出预算')
            for command in frame:
                _command(command)
                asset(command['asset'], 'image')
        layers = model.get('layers', {})
        if not isinstance(layers, dict):
            raise StudioError('参考图层无效')
        for layer in layers.values():
            if not isinstance(layer, dict):
                raise StudioError('参考图层无效')
            if layer.get('asset'):
                asset(layer['asset'], 'image')
            for key in ('x', 'y'):
                _finite(layer.get(key, 0), -4096, 4096)
        if 'channels' in model:
            validate_channels(model, project['assets'])
            # Bound the channel × output-frame work before the shared composer.
            if len(model['channels']) * model['channelDuration'] > 2000000:
                raise StudioError('参考通道合成超出预算')
            frames = compose_frames(model)
        else:
            for frame in source:
                commands = []
                for original in frame:
                    layer = layers.get(original['asset'], {})
                    if layer.get('visible') is False:
                        continue
                    command = copy.deepcopy(original)
                    command['asset'] = layer.get('asset') or command['asset']
                    command['fx'] = command.get('fx', 0) - layer.get('x', 0)
                    command['fy'] = command.get('fy', 0) - layer.get('y', 0)
                    commands.append(command)
                frames.append(commands)
    else:
        clips = model.get('clips', [])
        if not isinstance(clips, list) or not clips:
            raise StudioError('此参考还没有可播放画稿')
        for clip in clips:
            hold = integer(clip.get('hold'), 1, MAX_FRAMES, '参考停留帧数')
            if len(frames) + hold > MAX_FRAMES:
                raise StudioError('参考动作超过帧数预算')
            image = asset(clip.get('asset'), 'image')
            x = _finite(clip.get('x', 0), -4096, 4096)
            y = _finite(clip.get('y', 0), -4096, 4096)
            scale = _finite(clip.get('scale', 1), .05, 20)
            angle = math.radians(_finite(clip.get('rotation', 0), -360, 360))
            alpha = _finite(clip.get('opacity', 1), 0, 1)
            co, si = math.cos(angle) * scale, math.sin(angle) * scale
            flip = -1 if clip.get('flip') else 1
            w, h = image['width'], image['height']
            # Same order as drawClip: translate, scale, center, rotate, flip.
            command = {'asset': clip['asset'], 'matrix': [co * flip, si * flip, -si, co, x + w/2*scale, y + h/2*scale],
                       'alpha': alpha, 'fx': w/2, 'fy': h/2}
            frames.extend([[copy.deepcopy(command)] for _ in range(hold)])
    if sum(map(len, frames)) > MAX_COMMANDS:
        raise StudioError('参考合成指令超出预算')
    for frame in frames:
        for command in frame:
            _command(command)
            asset(command['asset'], 'image')
    events = model.get('soundEvents', [])
    if not isinstance(events, list) or len(events) > 5000:
        raise StudioError('参考声音事件超限')
    for event in events:
        if event.get('enabled') is False:
            continue
        sound = asset(event.get('asset'), 'audio')
        start = integer(event.get('start'), 0, MAX_FRAMES - 1, '参考声音开始帧')
        end = integer(event.get('end', -1), -1, MAX_FRAMES, '参考声音结束帧')
        if end >= 0 and end <= start:
            raise StudioError('参考声音结束帧无效')
        result['audio'].append({'start': start, 'end': end,
                                'volume': number(event.get('volume', 1), 0, 1, '参考音量'),
                                'loop': integer(event.get('loop', 1), -1, 100, '参考播放次数'),
                                'rate': 1, 'url': sound['url'], 'sha256': sound['sha256']})
    result['frames'] = frames
    result['issues'].extend(str(issue) for issue in model.get('issues', []))
    if any(cmd.get('blend', 0) for frame in frames for cmd in frame):
        result['issues'].append('特殊混合模式仍待核；画面沿用工坊现有绘制方式。')
    result['issues'].append('这是已保存声画素材参考；完整技能、目标、跟随和游戏行为仍需制作方验证。')
    result['status'] = 'pending' if model.get('issues') or input_issues else 'media-ready'
    return result
