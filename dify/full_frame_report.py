"""Fail-closed report for a separately implemented full-frame analysis service.

Coverage is asserted by the service, not inferred from an LLM response. All
frame numbers are one-based decoder output indices. Audio observations must be
produced by an audio-capable analysis of the actual soundtrack, not ASR alone.
"""
import json
import math

RUBRIC = [('opening', '开头吸引力'), ('content', '内容价值与故事'),
          ('visual_match', '画面与内容匹配'), ('editing', '剪辑节奏与完整度'),
          ('sound', '配音与声音'), ('subtitle', '字幕与手机观看体验'),
          ('cta', '行动引导与分享意愿')]
RISK_TYPES = {'face', 'flag', 'logo'}


def _object(value):
    try:
        obj = json.loads(value) if isinstance(value, str) else value
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _observations(rows, kind, count):
    found, duplicate = {}, set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key, description = row.get('id'), row.get('observation')
        if not isinstance(key, str) or not key or not isinstance(description, str) or not description.strip():
            continue
        if kind == 'visual':
            n, t = row.get('frame'), row.get('time_sec')
            if type(n) is not int or not 1 <= n <= count or not _number(t) or t < 0:
                continue
        if key in found:
            duplicate.add(key)
        found[key] = row
    return {key: row for key, row in found.items() if key not in duplicate}


def main(coverage_json: str, visual_json: str, audio_json: str, score_json: str) -> dict:
    coverage, visual, audio, score = map(_object, (coverage_json, visual_json, audio_json, score_json))
    count = coverage.get('total_frames')
    checked, failed = coverage.get('checked_frames'), coverage.get('failed_frames')
    coverage_ok = (coverage.get('status') == 'ok' and type(count) is int and count > 0
                   and isinstance(checked, list) and len(checked) == count
                   and all(type(n) is int and 1 <= n <= count for n in checked)
                   and len(set(checked)) == count and failed == [])
    count = count if type(count) is int and count > 0 else 0
    observations = _observations(visual.get('observations'), 'visual', count)
    audio_ok = audio.get('status') == 'ok' and audio.get('source') == 'audio_analysis'
    audio_observations = _observations(audio.get('observations'), 'audio', count) if audio_ok else {}

    risks = visual.get('risks')
    risks_ok = isinstance(risks, list) and all(
        isinstance(row, dict) and isinstance(row.get('type'), str) and row.get('type') in RISK_TYPES
        and type(row.get('frame')) is int and 1 <= row['frame'] <= count
        and isinstance(row.get('description'), str) and bool(row['description'].strip())
        for row in risks)
    coverage_ok = coverage_ok and visual.get('status') == 'ok' and risks_ok
    risks = risks if risks_ok else []

    rows, duplicate = {}, set()
    for row in score.get('criteria', []) if isinstance(score.get('criteria'), list) else []:
        if isinstance(row, dict) and isinstance(row.get('id'), str):
            key = row['id']
            if key in rows:
                duplicate.add(key)
            rows[key] = row
    values = {}
    for key, _ in RUBRIC:
        row = rows.get(key, {})
        value, evidence = row.get('score'), row.get('evidence')
        valid = (_number(value) and 0 <= value <= 100 and key not in duplicate
                 and isinstance(evidence, list) and bool(evidence))
        refs_v, refs_a = [], []
        if valid:
            for ref in evidence:
                if (not isinstance(ref, dict) or set(ref) != {'source', 'id'}
                        or not isinstance(ref['id'], str)):
                    valid = False
                    break
                if ref['source'] == 'visual' and ref['id'] in observations:
                    refs_v.append(observations[ref['id']])
                elif ref['source'] == 'audio' and ref['id'] in audio_observations:
                    refs_a.append(audio_observations[ref['id']])
                else:
                    valid = False
                    break
        if key == 'opening':
            valid = valid and any(r['time_sec'] < 3 for r in refs_v)
        elif key == 'visual_match':
            valid = valid and bool(refs_v) and any(r['id'] == 'a_speech' for r in refs_a)
        elif key == 'editing':
            valid = valid and len({r['frame'] for r in refs_v}) >= 2
        elif key == 'sound':
            valid = valid and bool(refs_a)
        elif key == 'subtitle':
            valid = valid and bool(refs_v)
        else:
            valid = valid and bool(refs_v or refs_a)
        values[key] = value if valid else None

    complete = all(v is not None for v in values.values())
    total = sum(values.values()) / len(RUBRIC) if complete else None
    passed = coverage_ok and complete and total >= 80 and not risks
    verdict = '通过' if passed else '转人工'
    lines = ['## 评分', '综合评分：' + (format(total, '.12g') + ' / 100' if complete else '待确认')]
    lines += [name + '：' + (format(values[key], '.12g') + ' / 100' if values[key] is not None else '待确认')
              for key, name in RUBRIC]
    lines += ['', '## 安全、转人工', '结果：' + verdict]
    if not coverage_ok:
        lines.append('全帧检测未完成或检测结果无效。')
    if not complete:
        lines.append('评分证据不足。')
    elif total < 80:
        lines.append('综合评分低于 80 分。')
    for risk in risks:
        lines.append('风险提示：' + risk['type'] + '，第 ' + str(risk['frame']) + ' 帧：' + risk['description'].strip())
    if passed:
        lines.append('全部帧已完成检测，未检出指定风险；AI 检测仍可能漏识别。')
    return {'report': '\n'.join(lines), 'verdict': verdict, 'total': total,
            'coverage_complete': coverage_ok, 'scores': values}
