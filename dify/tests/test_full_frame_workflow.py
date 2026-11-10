import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

h = load('full_frame_workflow_nodes')
builder = load('build_full_frame_workflow')


class FullFrameWorkflowTest(unittest.TestCase):
    def test_preparation_and_job_url(self):
        result = h.prepare('https://files.example/video.mp4', '', '', 'en-US', 'https://service.example/api')
        self.assertEqual(result['submit_url'], 'https://service.example/api/jobs')
        self.assertEqual(json.loads(result['body'])['video_url'], 'https://files.example/video.mp4')
        self.assertEqual(h.prepare('http://file', '', '', '', 'https://service.example')['ready'], 0)
        self.assertEqual(h.prepare('https://file', '', '', '', 'http://service.example')['ready'], 0)
        self.assertEqual(h.parse_submit('{"job_id":"../etc"}', 202, result['base_url'])['ready'], 0)
        self.assertEqual(h.parse_submit('{"job_id":"test-1"}', 202, result['base_url'])['poll_url'], 'https://service.example/api/jobs/test-1')

    def test_poll_fails_closed(self):
        def poll(result):
            return h.parse_poll(json.dumps({'status':'succeeded','result':result}), 200)
        self.assertEqual(h.parse_poll('{"status":"running"}', 200)['done'], 0)
        base = {'report':'ok', 'verdict':'通过', 'total':85, 'coverage_complete':True}
        self.assertEqual(poll(base)['report'], 'ok')
        for change in ({'total':79}, {'total':True}, {'coverage_complete':False}, {'verdict':'bad'}, {'report':''}):
            data = dict(base, **change)
            self.assertNotEqual(poll(data)['report'], 'ok')
        self.assertIn('失败', h.parse_poll('{"status":"failed"}', 200)['report'])
        self.assertIn('超时', h.output(0, '')['report'])

    def test_generated_graph_uses_only_secret_in_http_headers(self):
        dsl = builder.build()
        variables = {v['name']: v for v in dsl['workflow']['environment_variables']}
        self.assertEqual(variables['FULL_FRAME_API_KEY']['value_type'], 'secret')
        self.assertEqual(variables['FULL_FRAME_API_KEY']['value'], '')
        nodes = {n['id']: n for n in dsl['workflow']['graph']['nodes']}
        for name in ('submit', 'poll'):
            self.assertIn('{{#env.FULL_FRAME_API_KEY#}}', nodes[name]['data']['headers'])
            self.assertEqual(nodes[name]['data']['error_strategy'], 'default-value')
        for n in nodes.values():
            if n['data']['type'] == 'code':
                self.assertNotIn('FULL_FRAME_API_KEY', str(n['data'].get('variables')))
        self.assertEqual(nodes['loop']['data']['loop_count'], 100)
        self.assertEqual(nodes['end']['data']['outputs'][0]['value_type'], 'string')


if __name__ == '__main__':
    unittest.main()
