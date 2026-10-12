"""Read-only, exact author-reference choices; no gameplay replacement or compile.

Evidence: native_dependencies fields[7] and ActionDslAssetResolver collectors;
complex-dependencies-20261011/evidence/real-multiball-verification.json;
ui-dependencies-20261011/evidence/RETAINED-MOD-AUTHOR-SCOPE-VERIFICATION.md.
Only declared project reference members and selected objects' declared assets
are read. Common scene/UI roots are never added. Frozen resource checks do not
prove counts, lifetime, targeting, animation semantics or battle execution.
"""
from __future__ import annotations

import copy
import hashlib
import re

from character_dependencies import canonical, resource_catalog, analyze, _path, _decode_json
from native_dependencies import _program, resolve_command_resources

MAX_ITEMS = 5000
MAX_BYTES = 128 * 1024 * 1024
FILE_BYTES = 16 * 1024 * 1024


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _walk(value):
    pending, count = [(value, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > 100000 or depth > 128:
            raise ValueError('参考对象嵌套或条目超限')
        yield node
        if isinstance(node, dict):
            pending.extend((item, depth + 1) for item in node.values())
        elif isinstance(node, list):
            pending.extend((item, depth + 1) for item in node)


def _read(store, project, group, name, budget):
    _path(name)
    root = store.directory(project['id']).resolve()
    folder = (root / group).resolve()
    target = (folder / name).resolve()
    if not folder.is_relative_to(root) or not target.is_relative_to(folder):
        raise ValueError('参考文件越出工程范围')
    size = target.stat().st_size
    if not target.is_file() or size > FILE_BYTES or budget[0] + size > MAX_BYTES:
        raise ValueError('参考输入大小超限')
    raw = target.read_bytes()
    budget[0] += len(raw)
    if len(raw) != size or budget[0] > MAX_BYTES:
        raise ValueError('参考读取期间文件变化或输入超限')
    return raw


def _inputs(store, project):
    files, issues, budget = {}, [], [0]
    names = project.get('referenceFiles', [])
    if not isinstance(names, list) or len(names) > MAX_ITEMS:
        return files, {}, [{'reason': '声明参考清单无效或超限'}], budget
    seen = set()
    for name in names:
        try:
            _path(name)
            if name in seen:
                raise ValueError('声明参考路径重复')
            seen.add(name)
            files[name] = _read(store, project, 'reference', name, budget)
        except (ValueError, OSError, KeyError) as exc:
            issues.append({'logical': str(name), 'reason': str(exc)})
    catalog = resource_catalog(files)
    # Existing exports provide an explicit logical -> tree mapping. A readable
    # receipt never replaces an actual compressed program's byte identity.
    for name, raw in files.items():
        if name == 'data_readable/skill_dependencies.json' or (name.startswith('data_readable/action_dsl/decoded/') and name.endswith('.json')):
            try:
                data = _decode_json(raw)
                programs = data.get('programs') if name.endswith('skill_dependencies.json') else [{'logical': data.get('logical_path'), 'tree': data.get('tree')}]
                if not isinstance(programs, list) or len(programs) > MAX_ITEMS:
                    raise ValueError('明确program映射无效或超限')
                for item in programs:
                    logical = _program(item.get('logical'))
                    tree = item.get('tree')
                    if not isinstance(tree, (dict, list)):
                        raise ValueError('明确program映射缺tree')
                    old = catalog.get(logical)
                    if old:
                        if old.get('kind') != 'dsl' or old.get('data') != tree:
                            old['decodeError'] = '同program逻辑身份树冲突'
                    else:
                        catalog[logical] = {'kind': 'dsl', 'data': tree, 'sha256': _sha(raw),
                                            'source': name, 'mappingSource': name, 'mappingSha256': _sha(raw)}
            except (ValueError, TypeError, AttributeError, RecursionError) as exc:
                issues.append({'logical': name, 'reason': str(exc)})
    if 'audio_catalog.json' in files:
        try:
            items = _decode_json(files['audio_catalog.json']).get('items', [])
            if not isinstance(items, list) or len(items) > MAX_ITEMS:
                raise ValueError('声音映射无效或超限')
            for item in items:
                logical, source = _path(item.get('logical')), item.get('file')
                alias = logical if logical.endswith('.mp3') else logical + '.mp3'
                if source in catalog and catalog[source].get('kind') == 'sound':
                    mapped = {**catalog[source], 'mappingSource': 'audio_catalog.json'}
                    if alias in catalog and catalog[alias]['sha256'] != mapped['sha256']:
                        catalog[alias]['decodeError'] = '声音logical身份冲突'
                    else:
                        catalog.setdefault(alias, mapped)
        except (ValueError, TypeError, AttributeError) as exc:
            issues.append({'logical': 'audio_catalog.json', 'reason': str(exc)})
    # The existing reference exporter maps a typed effect logical to a hashed
    # parts filename. Use that proven adapter only when its exact member exists.
    from skill_preview import effect_path
    for record in list(catalog.values()):
        if record.get('kind') != 'dsl' or record.get('decodeError'):
            continue
        try:
            for node in _walk(record.get('data')):
                if isinstance(node, list) and len(node) == 2 and node[0] == 'SpecifyEffectDirectly' and isinstance(node[1], str):
                    name = effect_path(node[1])
                    if name in catalog:
                        mapped = {'kind': 'effect', 'sha256': catalog[name]['sha256'], 'source': name,
                                  'data': {'parts': name, 'timeline': name.replace('.parts.json', '.timeline.json')}}
                        old = catalog.get(node[1])
                        if old is not None and old != mapped:
                            old['decodeError'] = 'effect逻辑映射冲突'
                        else:
                            catalog.setdefault(node[1], mapped)
        except (ValueError, TypeError, RecursionError) as exc:
            issues.append({'reason': 'effect明确映射待核：' + str(exc)})
    return files, catalog, issues, budget


def _options(project, catalog, issues):
    entries = []
    native = project.get('nativeGameplay')
    if native is not None:
        try:
            import native_gameplay
            native_gameplay.validate_native(native, draft=True)
            source_character = native['source']['data']['character']
            cr = source_character['records']['character']['selected'][source_character['id']]['rows'][0]
            element = int(cr[3]) if cr[3].isdigit() and 0 <= int(cr[3]) <= 6 else None
            keys = [row['inner_key'] for row in native['skills']]
            for index, row in enumerate(native['skills']):
                if keys.count(row['inner_key']) > 1:
                    issues.append({'reason': '真实技能版本键重复，不能明确绑定'}); continue
                fields = row['fields']
                logical = _program(fields[7])
                entry = {'kind': 'skill', 'key': row['inner_key'], 'pointer': '/nativeGameplay/skills/' + str(index),
                         'model': row, 'logical': logical, 'element': element, 'sourceSha256': native['source']['sha256'],
                         'label': (fields[0] or '主动技能') + ' · 版本 ' + str(index + 1)}
                entries.append(entry)
                record = catalog.get(logical, {})
                if record.get('decodeError'):
                    continue
                summon_index = 0
                for node in _walk(record.get('data')):
                    if isinstance(node, list) and node and node[0] in ('CreateSummonsMultiball', 'SpawnFunnel'):
                        mapped = resolve_command_resources(node)
                        definition = next((d for d in mapped['requiredDefinitions'] if d['kind'] in ('Multiball', 'Funnel', 'Zako', 'StandardFunnel')), None)
                        if definition:
                            summon_index += 1
                            title = {'Multiball': '召唤物', 'Funnel': '跟随物', 'Zako': '小怪', 'StandardFunnel': '特殊跟随物'}[definition['kind']]
                            entries.append({'kind': 'summon', 'key': [row['inner_key'], node], 'model': node,
                                            'pointer': entry['pointer'], 'logical': logical,
                                            'element': element, 'sourceSha256': native['source']['sha256'],
                                            'definitionKind': definition['kind'], 'definitionKey': definition['key'],
                                            'label': entry['label'] + ' · ' + title + '参考 ' + str(summon_index)})
        except (ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
            issues.append({'reason': '真实技能参考待核：' + str(exc)})
    for group, kind, title in (('animations', 'animation', '动作'), ('effects', 'effect', '特效'), ('sounds', 'sound', '声音')):
        rows = project.get(group, [])
        if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
            issues.append({'reason': title + '清单无效或超限'}); continue
        ids = [item.get('id') for item in rows if isinstance(item, dict)]
        duplicates = {key for key in ids if ids.count(key) > 1}
        for index, item in enumerate(rows):
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in duplicates:
                issues.append({'reason': title + '对象缺唯一键'}); continue
            entries.append({'kind': kind, 'key': item['id'], 'model': item, 'pointer': '/' + group + '/' + str(index),
                            'label': title + ' · ' + str(item.get('name') or item.get('slot') or item['id'])})
    if len(entries) > MAX_ITEMS:
        raise ValueError('复用候选超限')
    for entry in entries:
        entry['id'] = 'reuse-' + _sha(canonical([entry['kind'], entry['key'], entry['model']]))[:32]
    # The same summon command can occur repeatedly; its exact choice is one
    # reference, rather than an inferred runtime occurrence count.
    return list({entry['id']: entry for entry in entries}.values())


def _snapshot(store, project):
    files, resources, issues, budget = _inputs(store, project)
    entries = _options(project, resources, issues)
    assets = project.get('assets', {})
    if not isinstance(assets, dict):
        assets = {}; issues.append({'reason': '素材清单无效'})
    cached_assets = {}
    for entry in entries:
        local, local_issues, used = {}, [], {}
        try:
            nodes = list(_walk(entry['model']))
        except ValueError as exc:
            nodes = []
            local_issues.append({'reason': str(exc)})
        for node in nodes:
            if not isinstance(node, dict) or 'asset' not in node:
                continue
            aid = node['asset']
            if aid is None:
                local_issues.append({'reason': '所选对象存在未绑定素材'}); continue
            if not isinstance(aid, str) or aid not in assets:
                local_issues.append({'reason': '所选对象引用的素材不存在', 'asset': str(aid)}); continue
            if aid in used:
                continue
            try:
                meta = assets[aid]
                name = _path(meta['file'])
                if name not in cached_assets:
                    cached_assets[name] = _read(store, project, 'assets', name, budget)
                raw = cached_assets[name]
                logical = 'project-assets/' + name
                local[logical] = raw
                used[aid] = logical
                if meta.get('sha256') != _sha(raw):
                    local_issues.append({'logical': logical, 'reason': '素材实际字节与登记SHA不一致'})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                local_issues.append({'asset': aid, 'reason': str(exc)})
        input_identity = [{'logical': name, 'sha256': _sha(raw), 'bytes': len(raw)} for name, raw in sorted({**files, **local}.items())]
        model_sha = _sha(canonical(entry['model']))
        entry['identity'] = {'sha256': _sha(canonical([entry['kind'], entry['key'], model_sha, input_identity, issues, local_issues])),
                             'modelSha256': model_sha, 'pointer': entry['pointer'], 'inputs': input_identity,
                             'kind': entry['kind'], 'modelKey': copy.deepcopy(entry['key'])}
        for field in ('definitionKind', 'definitionKey'):
            if field in entry:
                entry['identity'][field] = entry[field]
        if 'sourceSha256' in entry:
            entry['identity']['sourceSha256'] = entry['sourceSha256']
            entry['identity']['sha256'] = _sha(canonical([entry['identity']['sha256'], entry['sourceSha256'], entry['element']]))
        entry.update(local=local, localIssues=local_issues, assets=used)
    return entries, files, resources, issues


def catalog(store, project):
    try:
        entries, _, _, issues = _snapshot(store, project)
        options = []
        for item in entries:
            identity = {key: item['identity'][key] for key in ('sha256', 'modelSha256', 'sourceSha256', 'pointer') if key in item['identity']}
            identity['inputCount'] = len(item['identity']['inputs'])
            options.append({**{key: item[key] for key in ('id', 'label', 'kind')}, 'identity': identity})
        return {'options': options,
                'issues': issues, 'gameReady': False}
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        return {'options': [], 'issues': [{'reason': str(exc)}], 'gameReady': False}


def inspect(store, project, choice, digest=None):
    result = {'status': 'pending', 'label': '', 'identity': None, 'evidence': [], 'counts': {},
              'missing': [], 'dynamic': [], 'unsupported': [], 'gameReady': False, 'behaviorVerified': False}
    try:
        entries, files, resources, issues = _snapshot(store, project)
        selected = next((item for item in entries if item['id'] == choice), None)
        if selected is None:
            raise ValueError('所选参考不存在或原对象已变化；请重新明确选择')
        result.update(label=selected['label'], identity=selected['identity'])
        if digest is not None and digest != selected['identity']['sha256']:
            raise ValueError('参考输入身份已变化；请重新检查并明确选择')
        for name, record in resource_catalog(selected['local']).items():
            if name in resources and (resources[name]['sha256'] != record['sha256'] or resources[name].get('decodeError')):
                record['decodeError'] = '参考与本地素材logical身份冲突'
            resources[name] = record
        definitions = {}
        for name, raw in files.items():
            logical = re.sub(r'^compiled/(?:common|medium|android|ios)/', '', name)
            record = resources.get(logical, {})
            if not record.get('decodeError') and record.get('sha256') == _sha(raw):
                definitions[logical] = raw
        roots = []
        def root(logical, **extra):
            if extra.get('element') is None:
                extra.pop('element', None)
            roots.append({'logical': logical, 'requester': choice, 'source': selected['pointer'], 'category': selected['kind'],
                          'bucket': 'Project', 'collection': 'single-author-reference', 'layer': None, **extra})
        if selected['kind'] == 'skill':
            root(selected['logical'], kind='dsl', element=selected.get('element'))
        elif selected['kind'] == 'summon':
            mapped = resolve_command_resources(selected['model'], element=selected.get('element'), reference_files=definitions)
            for ref in mapped['references']:
                root(ref['logical'], **ref.get('context', {}))
            result['evidence'].append({'source': selected['logical'], 'command': copy.deepcopy(selected['model']),
                                       'definitions': mapped['requiredDefinitions'], 'coverage': mapped['coverage']})
            result['dynamic'].extend(mapped['problems'])
        else:
            for logical in selected['assets'].values():
                root(logical)
            model = selected['model']
            if model.get('sourceFile'):
                root(_path(model['sourceFile']))
            path = model.get('native', {}).get('path') if isinstance(model.get('native'), dict) else None
            if path:
                root(_path(path))
            for issue in model.get('issues', []):
                result['dynamic'].append({'reason': str(issue)})
        if not roots:
            result['missing'].append({'reason': '所选参考没有可检查的明确素材或程序来源'})
        report = analyze(roots, resources, {'kind': 'finite-resources'}, reference_files=definitions)
        result['evidence'].extend(report['dependencies'])
        result['evidence'].extend({'definition': item} for item in report['requiredDefinitions'])
        result['counts'] = report['counts']
        result['missing'].extend(report['missingReferences'])
        result['dynamic'].extend(report['unresolvedDynamic'])
        result['unsupported'].extend(report['unsupported'])
        result['unsupported'].extend(report['scopeGaps'])
        result['unsupported'].extend(issues + selected['localIssues'])
        result['counts'].update(missing=len(result['missing']), dynamic=len(result['dynamic']),
                                unsupported=len(result['unsupported']))
        if not any(result[key] for key in ('missing', 'dynamic', 'unsupported')) and roots:
            result['status'] = 'references_checked'
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
        result['unsupported'].append({'reason': str(exc)})
    return result
