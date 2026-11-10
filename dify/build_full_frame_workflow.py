"""Generate a credential-free Dify workflow for an external async service.

The service API contract is documented in FULL_FRAME_SERVICE_CONTRACT.md.
This only prepares a workflow; it does not deploy or test the service.
"""
from copy import deepcopy
from pathlib import Path
import uuid
import yaml

ROOT = Path(__file__).resolve().parent


def uid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'full-frame-cloud-workflow/' + name))


def build():
    dsl = yaml.safe_load((ROOT / 'team_video_review.yml').read_text(encoding='utf-8'))
    original = {n['id']: n for n in dsl['workflow']['graph']['nodes']}
    dsl['app']['name'] = '视频七维评测（云端全帧服务）'
    dsl['app']['description'] = '调用外部全帧服务的异步工作流；服务需要单独部署和验证。'
    dsl['dependencies'] = []
    workflow = dsl['workflow']
    workflow['environment_variables'] = [
        {'id': uid('url'), 'name': 'FULL_FRAME_BASE_URL', 'value_type': 'string', 'value': '',
         'description': '管理员填写已部署的 HTTPS 服务根地址，或以 /api 结尾的地址。'},
        {'id': uid('key'), 'name': 'FULL_FRAME_API_KEY', 'value_type': 'secret', 'value': '',
         'description': '服务鉴权密钥；请在 Dify 内填写，导出工作流前留空。'},
    ]
    nodes, edges = [], []
    helper = (ROOT / 'full_frame_workflow_nodes.py').read_text(encoding='utf-8')

    def node(ident, title, typ, data, x, y=300, parent=None):
        value = {'id': ident, 'data': {'desc': '', 'selected': False, 'title': title, 'type': typ, **data},
                 'position': {'x': x, 'y': y}, 'positionAbsolute': {'x': x, 'y': y},
                 'height': 120, 'width': 244, 'selected': False, 'sourcePosition': 'right',
                 'targetPosition': 'left', 'type': 'custom', 'zIndex': 0}
        if parent:
            value.update(parentId=parent, zIndex=1002)
            value['data'].update(isInIteration=False, isInLoop=True, loop_id=parent)
        nodes.append(value)
        return value

    def bind(key, selector, typ='string'):
        return {'variable': key, 'value_selector': selector, 'value_type': typ}

    def code(ident, title, function, variables, outputs, x, y=300, parent=None):
        return node(ident, title, 'code', {'code_language': 'python3', 'code': helper + '\nmain = ' + function + '\n',
                    'variables': variables, 'outputs': {k: {'type': t, 'children': None} for k, t in outputs.items()}}, x, y, parent)

    def branch(ident, title, selector, x):
        return node(ident, title, 'if-else', {'cases': [{'case_id': 'true', 'id': 'true', 'logical_operator': 'and',
                    'conditions': [{'id': uid(ident), 'comparison_operator': '=', 'value': '1',
                                    'varType': 'number', 'variable_selector': selector}]}]}, x)

    def http(ident, title, method, url, x, y=300, body=None, parent=None):
        data = deepcopy(original['get_frames']['data'])
        data.update(title=title, method=method, url=url,
                    headers='Authorization: Bearer {{#env.FULL_FRAME_API_KEY#}}',
                    authorization={'type': 'no-auth'}, timeout={'connect': 10, 'read': 30, 'write': 30},
                    error_strategy='default-value',
                    default_value=[{'key': 'body', 'type': 'string', 'value': ''},
                                   {'key': 'status_code', 'type': 'number', 'value': '0'}])
        if body is None:
            data['body'] = {'type': 'none', 'data': []}
        else:
            data['headers'] += '\nContent-Type: application/json'
            data['body'] = {'type': 'json', 'data': [{'id': uid(ident+'body'), 'key': '', 'type': 'text', 'value': body}]}
        return node(ident, title, 'http-request', data, x, y, parent)

    def edge(source, target, handle='source', parent=None):
        kinds = {n['id']: n['data']['type'] for n in nodes}
        data = {'isInIteration': False, 'isInLoop': bool(parent), 'sourceType': kinds[source], 'targetType': kinds[target]}
        if parent:
            data['loop_id'] = parent
        edges.append({'id': source+'-'+handle+'-'+target, 'source': source, 'sourceHandle': handle,
                      'target': target, 'targetHandle': 'target', 'type': 'custom', 'data': data,
                      'zIndex': 1002 if parent else 0})

    start = deepcopy(original['start'])
    start['position'] = start['positionAbsolute'] = {'x': 20, 'y': 300}
    start['data']['variables'] = [v for v in start['data']['variables'] if v['variable'] in ('video', 'script', 'rules', 'asr_language')]
    for v in start['data']['variables']:
        if v['variable'] != 'video':
            v['required'] = False
        if v['variable'] == 'rules':
            v['default'] = ('检测视频各帧中可识别的人脸、国旗以及疑似品牌标识。'
                            '发现疑似风险时应转人工；竞品身份无法确认时不得假称已确认。')
    nodes.append(start)
    code('prepare', '准备全帧任务', 'prepare', [bind('video_url',['start','video','url']),
         bind('script',['start','script']), bind('rules',['start','rules']), bind('language',['start','asr_language']),
         bind('base_url',['env','FULL_FRAME_BASE_URL'])], {'ready':'number','submit_url':'string','base_url':'string','body':'string'}, 340)
    branch('configured', '服务地址有效', ['prepare','ready'], 660)
    http('submit', '提交全帧任务', 'post', '{{#prepare.submit_url#}}', 980, body='{{#prepare.body#}}')
    code('submitted', '校验任务编号', 'parse_submit', [bind('body',['submit','body']), bind('status',['submit','status_code'],'number'),
         bind('base_url',['prepare','base_url'])], {'ready':'number','poll_url':'string'}, 1300)
    branch('accepted', '任务已受理', ['submitted','ready'], 1620)
    loop = node('loop', '等待全帧服务（最多100次，每次10秒）', 'loop', {
        'break_conditions':[{'id':uid('done'),'comparison_operator':'≥','value':'1','varType':'number','variable_selector':['loop','done']}],
        'logical_operator':'and','loop_count':100,'start_node_id':'loopstart',
        'loop_variables':[{'id':uid(k),'label':k,'value':v,'value_type':'constant','var_type':t}
                          for k,v,t in [('done','0','number'),('report','','string')]], 'width':1400,'height':330},1940)
    loop.update(width=1400, height=330, zIndex=1)
    ls=node('loopstart','','loop-start',{},40,120,'loop')
    ls.update(type='custom-loop-start',height=48,width=44,draggable=False,selectable=False)
    node('pause','等待10秒','code',{'code_language':'python3','code':'import time\n\ndef main() -> dict:\n    time.sleep(10)\n    return {"ready": 1}\n','variables':[],
         'outputs':{'ready':{'type':'number','children':None}}},120,120,'loop')
    http('poll', '查询任务状态', 'get', '{{#submitted.poll_url#}}', 420,120,parent='loop')
    code('poll_parse','校验服务结果','parse_poll',[bind('body',['poll','body']),bind('status',['poll','status_code'],'number')],
         {'done':'number','report':'string'},730,120,'loop')
    node('assign','保存任务状态','assigner',{'version':'2','items':[
         {'input_type':'variable','operation':'over-write','write_mode':'over-write','value':['poll_parse',k],
          'variable_selector':['loop',k]} for k in ('done','report')]},1040,120,'loop')
    code('done','输出处理结果','output',[bind('done',['loop','done'],'number'),bind('report',['loop','report'])],{'report':'string'},3460)
    err = 'def main() -> dict:\n    return {"report": "全帧服务未配置或任务提交失败，本次不生成评分。"}\n'
    for ident,x in [('unconfigured',980),('rejected',1940)]:
        node(ident,'服务不可用','code',{'code_language':'python3','code':err,'variables':[],
             'outputs':{'report':{'type':'string','children':None}}},x,760)
    node('aggregate','汇总结果','variable-aggregator',{'advanced_settings':{'group_enabled':False,'groups':[]},
         'output_type':'string','variables':[[k,'report'] for k in ('done','unconfigured','rejected')]},3780)
    end=deepcopy(original['end'])
    end['position']=end['positionAbsolute']={'x':4100,'y':300}
    end['data']['outputs']=[{'variable':'report','value_type':'string','value_selector':['aggregate','output']}]
    nodes.append(end)
    for a,b in [('start','prepare'),('prepare','configured'),('submit','submitted'),('submitted','accepted'),
                ('loop','done'),('done','aggregate'),('unconfigured','aggregate'),('rejected','aggregate'),('aggregate','end')]:
        edge(a,b)
    for a,b,c in [('configured','submit','unconfigured'),('accepted','loop','rejected')]:
        edge(a,b,'true'); edge(a,c,'false')
    for a,b in [('loopstart','pause'),('pause','poll'),('poll','poll_parse'),('poll_parse','assign')]:
        edge(a,b,parent='loop')
    for n in nodes:
        if n.get('parentId') == 'loop':
            n['positionAbsolute']={'x':1940+n['position']['x'],'y':300+n['position']['y']}
    workflow['graph']={'nodes':nodes,'edges':edges,'viewport':{'x':0,'y':0,'zoom':0.45}}
    return dsl


if __name__ == '__main__':
    target=ROOT/'team_video_review_full_frame.yml'
    target.write_text(yaml.safe_dump(build(),allow_unicode=True,sort_keys=False,width=110),encoding='utf-8')
    print(target)
