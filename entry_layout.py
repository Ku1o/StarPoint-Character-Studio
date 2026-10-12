"""Plain-text NewEntry candidates. Geometry is an approximation, never acceptance."""
import difflib
import unicodedata


def _advance(char, font_size):
    if unicodedata.combining(char):
        return 0
    return font_size if unicodedata.east_asian_width(char) in ('W', 'F', 'A') else font_size * .55


def preview(original, candidate=None, width=360, height=116, font_size=20, line_height=26):
    if not isinstance(original, str) or len(original) > 4000:
        raise ValueError('获取原文必须为不超过 4000 字符的纯文本')
    candidate = original if candidate is None else candidate
    if not isinstance(candidate, str) or len(candidate) > 4000:
        raise ValueError('排版候选必须为不超过 4000 字符的纯文本')
    for value, low, high in ((width, 40, 2000), (height, 20, 2000), (font_size, 6, 100), (line_height, 6, 200)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError('气泡估算尺寸无效')
    lines, line, used = [], '', 0
    for char in candidate:
        if char == '\n':
            lines.append(line); line, used = '', 0
        else:
            advance = _advance(char, font_size)
            if line and used + advance > width:
                lines.append(line); line, used = '', 0
            line += char; used += advance
    lines.append(line)
    changes = [{'operation': tag, 'original': original[a:b], 'candidate': candidate[c:d],
                'originalRange': [a, b], 'candidateRange': [c, d]}
               for tag, a, b, c, d in difflib.SequenceMatcher(None, original, candidate, autojunk=False).get_opcodes() if tag != 'equal']
    wording_changed = original.replace('\n', '').replace('\r', '') != candidate.replace('\n', '').replace('\r', '')
    return {'original': original, 'candidate': candidate, 'originalCharacters': len(original),
            'candidateCharacters': len(candidate), 'lines': lines, 'lineCount': len(lines),
            'overflow': len(lines) * line_height > height, 'changes': changes, 'wordingChanged': wording_changed,
            'width': width, 'height': height, 'fontSize': font_size, 'lineHeight': line_height,
            'approximate': True, 'nativeVerified': False,
            'note': '使用字符宽度估算，字体、气泡几何及换行算法未与原生同构；字数和行数不能作为通用上限。'}


def report(project):
    values = []
    for voice in project.get('voices', []):
        if voice.get('usage') != 'join':
            continue
        saved = voice.get('entryLayout', {})
        if not isinstance(saved, dict):
            raise ValueError('获取排版候选必须为对象')
        original = saved.get('original', voice.get('text', ''))
        result = preview(original, saved.get('candidate'), **{key: saved[key] for key in ('width', 'height', 'font_size', 'line_height') if key in saved})
        result.update(id=voice['id'], authorConfirmed=saved.get('authorConfirmed') is True)
        values.append(result)
    return {'schema': 'starpoint-entry-layout-v1', 'entries': values, 'nativeVerified': False}
