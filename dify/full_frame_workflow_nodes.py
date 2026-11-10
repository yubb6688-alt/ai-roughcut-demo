"""Pure Dify code-node helpers for the external async full-frame job contract."""
import json
import math
import re
from urllib.parse import urlsplit


def _obj(value):
    try:
        obj = json.loads(value)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def prepare(video_url: str, script: str, rules: str, language: str, base_url: str) -> dict:
    invalid = {'ready': 0, 'submit_url': '', 'base_url': '', 'body': '{}'}
    try:
        base = urlsplit(base_url.rstrip('/'))
        media = urlsplit(video_url)
        if (base.scheme != 'https' or not base.hostname or base.username or base.password
                or base.port not in (None, 443) or base.query or base.fragment or base.path not in ('', '/api')
                or media.scheme != 'https' or not media.hostname or media.username or media.password or media.fragment):
            return invalid
        base_path = 'https://' + base.netloc + (base.path or '')
        body = {'video_url': video_url, 'script': script or '', 'rules': rules or '', 'language': language or 'en-US'}
        return {'ready': 1, 'submit_url': base_path + '/jobs', 'base_url': base_path,
                'body': json.dumps(body, ensure_ascii=False)}
    except (ValueError, TypeError, AttributeError):
        return invalid


def parse_submit(body: str, status: int, base_url: str) -> dict:
    invalid = {'ready': 0, 'poll_url': ''}
    data = _obj(body)
    job_id = data.get('job_id')
    if status not in (200, 201, 202) or not isinstance(job_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', job_id):
        return invalid
    return {'ready': 1, 'poll_url': base_url + '/jobs/' + job_id}


def parse_poll(body: str, status: int) -> dict:
    failed = {'done': 1, 'report': '检测任务失败或返回数据无效，请稍后重试；本次不生成评分。'}
    data = _obj(body)
    if status != 200:
        return failed
    state = data.get('status')
    if state in ('pending', 'running'):
        return {'done': 0, 'report': ''}
    result = data.get('result')
    if state != 'succeeded' or not isinstance(result, dict):
        return failed
    report = result.get('report')
    verdict = result.get('verdict')
    total = result.get('total')
    if (not isinstance(report, str) or not report.strip() or len(report) > 100000
            or verdict not in ('通过', '转人工') or type(result.get('coverage_complete')) is not bool
            or (verdict == '通过' and (result['coverage_complete'] is not True
                or type(total) not in (int, float) or not math.isfinite(total) or not 80 <= total <= 100))):
        return failed
    return {'done': 1, 'report': report}


def output(done: int, report: str) -> dict:
    if done == 1 and isinstance(report, str) and report.strip():
        return {'report': report}
    return {'report': '检测任务仍在处理中或已超时，本次不生成评分；请联系服务管理员查询任务状态。'}
