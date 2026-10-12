"""Full decoded audio measurements and explicit candidates; originals are immutable."""
from __future__ import annotations

import array
import copy
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

_CACHE = {}


def _run(args):
    try:
        result = subprocess.run(args, capture_output=True, timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('声音解码/测量超过 45 秒，原稿保留，测量待核') from exc
    if result.returncode:
        raise ValueError('声音解码/测量失败：' + result.stderr.decode('utf-8', 'replace')[-1000:])
    return result


def _finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def measure(raw, mono=True):
    """Decode the complete first audio stream, never infer metrics from encoder goals."""
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise ValueError('未找到 ffmpeg/ffprobe，声音测量待核；原稿仍可保存交接')
    digest = hashlib.sha256(raw).hexdigest()
    cache_key = (digest, mono)
    if cache_key in _CACHE:
        return copy.deepcopy(_CACHE[cache_key])
    with tempfile.TemporaryDirectory(prefix='studio-audio-review-') as temporary:
        path = Path(temporary) / 'input.audio'
        path.write_bytes(raw)
        info = json.loads(_run([ffprobe, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,codec_name,sample_rate,channels', '-of', 'json', str(path)]).stdout)
        stream = next((row for row in info.get('streams', []) if row.get('codec_type') == 'audio'), None)
        if not stream:
            raise ValueError('文件没有可解码音轨')
        channels, rate = int(stream['channels']), int(stream['sample_rate'])
        duration = _finite(info.get('format', {}).get('duration'))
        if duration is None or duration > 600:
            raise ValueError('测量仅支持有确定时长且不超过 10 分钟的素材；长素材请分用途核验')
        if channels not in (1, 2):
            raise ValueError('当前同声道测量支持 mono/stereo；其他声道需明确下混方法')
        if duration * channels * rate > 32_000_000:
            raise ValueError('完整解码样本超过当前有界测量容量；请分用途核验，不做截断测量')
        # Clipping is measured on every native channel, before folding/resampling.
        decoded = _run([ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:a:0', '-vn', '-f', 'f32le', '-']).stdout
        samples = array.array('f'); samples.frombytes(decoded)
        peak = max((abs(float(value)) for value in samples), default=0)
        clipped = sum(abs(value) >= 1 for value in samples)
        fold = 'pan=mono|c0=0.5*c0+0.5*c1,' if mono and channels == 2 else ''
        result = _run([ffmpeg, '-hide_banner', '-nostats', '-i', str(path), '-map', '0:a:0', '-vn', '-af', fold + 'loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
        matched = re.search(r'\{\s*"input_i".*?\}', result.stderr.decode('utf-8', 'replace'), re.S)
        if not matched:
            raise ValueError('未取得完整声音响度读数')
        loud = json.loads(matched.group())
        measured = {'sha256': digest, 'sourceChannels': channels, 'sampleRate': rate, 'codec': stream['codec_name'],
                    'measurementChannels': 1 if mono else channels,
                    'foldMethod': 'L/2+R/2' if mono and channels == 2 else 'native mono' if channels == 1 else 'native stereo',
                    'integratedLufs': _finite(loud['input_i']), 'truePeakDbtp': _finite(loud['input_tp']),
                    'lra': _finite(loud['input_lra']), 'samplePeak': peak, 'clippedSamples': clipped,
                    'decodedSeconds': len(samples) / channels / rate, 'containerSeconds': duration,
                    'fullDecode': True, 'silentOrTooShort': _finite(loud['input_i']) is None}
    if len(_CACHE) >= 128:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = measured
    return copy.deepcopy(measured)


def profile(project, kind='voice'):
    supplied = project.get('audioProfile', {})
    if not isinstance(supplied, dict):
        raise ValueError('声音配方必须为对象')
    row = supplied.get(kind, {})
    if not isinstance(row, dict):
        raise ValueError('语音/音效配方必须为对象')
    result = {'targetLufs': None, 'toleranceLu': 1, 'truePeakCeilingDbtp': None, 'paddingToleranceSeconds': .08, 'referenceAssetIds': []}
    result.update(copy.deepcopy(row))
    for key, low, high in (('targetLufs', -70, 0), ('toleranceLu', 0, 20), ('truePeakCeilingDbtp', -30, 0), ('paddingToleranceSeconds', 0, 1)):
        value = result[key]
        if value is None and key in ('targetLufs', 'truePeakCeilingDbtp'):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('声音配方数值无效：' + key)
    if not isinstance(result['referenceAssetIds'], list) or len(result['referenceAssetIds']) > 30 or not all(isinstance(aid, str) for aid in result['referenceAssetIds']):
        raise ValueError('同声道参考素材必须为最多 30 项的数组')
    return result


def project_report(store, project):
    from audio_compile import encoded_sound, sound_path
    from bridge import mp3_decode
    rows, refs = [], {}
    for kind in ('voice', 'sfx'):
        recipe = profile(project, kind)
        references = []
        for aid in recipe['referenceAssetIds']:
            try:
                references.append({'asset': aid, 'measure': measure(store.asset_bytes(project, aid))})
            except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                references.append({'asset': aid, 'status': 'blocked', 'error': str(exc)})
        measured_refs = [item['measure']['integratedLufs'] for item in references if item.get('measure', {}).get('integratedLufs') is not None]
        median = statistics.median(measured_refs) if measured_refs else None
        refs[kind] = {'profile': recipe, 'references': references, 'referenceMedianLufs': median, 'comparisonChannel': 'mono; stereo uses L/2+R/2'}
        records = list(project.get('voices' if kind == 'voice' else 'sounds', []))
        if kind == 'sfx':
            known = {item.get('asset') for item in records}
            for effect in project.get('effects', []):
                for event in effect.get('soundEvents', []):
                    aid = event.get('asset')
                    if aid and aid not in known and event.get('enabled') is not False:
                        records.append({'id': 'event_' + event['id'], 'asset': aid, 'name': effect['name'] + ' 声音事件', 'logical': event.get('path', '')})
                        known.add(aid)
            for track in project.get('scene', {}).get('tracks', []):
                aid = track.get('ref')
                if track.get('type') == 'audio' and aid not in known:
                    records.append({'id': 'track_' + track['id'], 'asset': aid, 'name': '演出声音轨道'})
                    known.add(aid)
        for voice in records:
            aid = voice.get('asset')
            row = {'id': voice.get('id'), 'asset': aid, 'kind': kind, 'name': voice.get('name', ''),
                   'logical': voice.get('logical') or sound_path(project.get('identity', {}).get('code', 'new_character'), aid),
                   'pathStatus': 'registered_evidence_supplied' if voice.get('registrationEvidence') else 'needs_native_registration',
                   'registrationEvidence': voice.get('registrationEvidence', ''), 'runtimeAccepted': False}
            try:
                raw = store.asset_bytes(project, aid)
                row['original'] = measure(raw)
                row['matchedReferenceDeltaLu'] = None if median is None or row['original']['integratedLufs'] is None else row['original']['integratedLufs'] - median
                if project['assets'][aid].get('mime') == 'audio/mpeg':
                    packed = encoded_sound(store, project, aid)
                    decoded = mp3_decode(packed)
                    row['encodedStorageSha256'] = hashlib.sha256(packed).hexdigest()
                    row['postEncodeDecode'] = measure(decoded)
                    row['packagingRoundtrip'] = decoded == raw
                    metrics = row['postEncodeDecode']
                    original_aid = voice.get('candidateOf')
                    if original_aid:
                        row['sourceOriginal'] = measure(store.asset_bytes(project, original_aid))
                    source = row.get('sourceOriginal', row['original'])
                    row['durationDeltaSeconds'] = metrics['decodedSeconds'] - source['decodedSeconds']
                    checks = {'clipping': metrics['clippedSamples'] == 0,
                              'duration': abs(row['durationDeltaSeconds']) <= recipe['paddingToleranceSeconds'],
                              'truePeak': None if recipe['truePeakCeilingDbtp'] is None or metrics['truePeakDbtp'] is None else metrics['truePeakDbtp'] <= recipe['truePeakCeilingDbtp'],
                              'loudness': None if recipe['targetLufs'] is None or metrics['integratedLufs'] is None else abs(metrics['integratedLufs'] - recipe['targetLufs']) <= recipe['toleranceLu']}
                    row['checks'] = checks
                    row['status'] = 'risk' if False in checks.values() else 'measured' if None in checks.values() else 'profile_pass'
                else:
                    row.update(status='handoff_only', note='WAV/OGG 原稿未编译；请显式生成 CBR 候选后再完整解码测量')
            except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as exc:
                row.update(status='blocked', error=str(exc))
            rows.append(row)
    return {'schema': 'starpoint-audio-review-v1', 'sourceRevision': project['revision'], 'rows': rows, 'references': refs,
            'gameReady': False, 'note': '同声道完整解码指标与全文、触发及听感分别验收；配方无目标时不判响度通过。'}


def create_candidate(store, pid, revision, aid, kind='voice'):
    from studio_core import StudioError
    if kind not in ('voice', 'sfx'):
        raise StudioError('候选用途必须为语音或音效')
    with store.lock:
        p = store.load(pid)
        if p['revision'] != revision:
            raise StudioError('工程已更新，请重新打开')
        recipe = profile(p, kind)
        if recipe['targetLufs'] is None or recipe['truePeakCeilingDbtp'] is None:
            raise StudioError('先填写当前角色配方的响度目标和编码后真峰上限，再生成候选')
        raw = store.asset_bytes(p, aid)
        before = measure(raw)
        if before['integratedLufs'] is None:
            raise StudioError('静音或过短素材不能按 LUFS 自动生成增益候选')
        gain = recipe['targetLufs'] - before['integratedLufs']
        if abs(gain) > 40:
            raise StudioError('增益超过 40 dB，请先核对原声和配方')
        ceiling = 10 ** ((recipe['truePeakCeilingDbtp'] - 2) / 20)
        ceiling = max(.063, min(1, ceiling))
        with tempfile.TemporaryDirectory(prefix='studio-audio-candidate-') as temporary:
            source, output = Path(temporary) / 'source.audio', Path(temporary) / 'candidate.mp3'
            source.write_bytes(raw)
            fold = 'pan=mono|c0=0.5*c0+0.5*c1,' if before['sourceChannels'] == 2 else ''
            filters = fold + f'aresample=44100,volume={gain}dB,alimiter=limit={ceiling}:level=false:latency=true'
            _run([shutil.which('ffmpeg'), '-y', '-v', 'error', '-i', str(source), '-map', '0:a:0', '-vn', '-af', filters,
                  '-ac', '1', '-ar', '44100', '-c:a', 'libmp3lame', '-b:a', '96k', '-write_xing', '0', '-map_metadata', '-1', str(output)])
            candidate = output.read_bytes()
        after = measure(candidate)
        source_mapping = next((row for row in p.get('sourceIntake', {}).get('derivatives', []) if row['asset'] == aid), None)
        if source_mapping is None:
            from source_intake import register_source
            record = register_source(p, p['assets'][aid]['name'], raw, metadata={'legacyAsset': aid})
            target = store.directory(pid) / record['blob']; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            source_id = record['id']
        else:
            source_id = source_mapping['source']
        cid = store.add_asset(p, 'candidate-' + p['assets'][aid]['name'].rsplit('.', 1)[0] + '.mp3', candidate, 'voice' if kind == 'voice' else 'sfx',
                              source={'sourceId': source_id, 'transform': {'operation': 'audio-candidate', 'inputAsset': aid, 'gainDb': gain, 'profile': recipe, 'fold': before['foldMethod']}})
        result = {'originalAsset': aid, 'candidateAsset': cid, 'profile': recipe, 'gainDb': gain,
                  'before': before, 'postEncodeDecode': after, 'durationDeltaSeconds': after['decodedSeconds'] - before['decodedSeconds'],
                  'originalPreserved': True, 'candidateNotApplied': True, 'nativeVerified': False}
        p.setdefault('audioCandidates', []).append(result)
        p['revision'] += 1
        store._write(p)
        return {'project': p, 'candidate': result}
