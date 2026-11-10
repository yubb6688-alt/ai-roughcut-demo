import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import full_frame_pipeline as pipeline


def video():
    frames = [{'frame': i, 'time_sec': i - 1, 'observation': '画面',
               'face': 'absent', 'flag': 'absent', 'logo': 'absent'} for i in (1, 2)]
    return {'complete': True, 'expected_frames': 2, 'failed_frames': [], 'frames': frames}


def audio():
    return {'status': 'ok', 'observations': [{'id': 'a1', 'observation': '说话清晰'},
            {'id': 'a2', 'observation': '语速适中'}, {'id': 'a3', 'observation': '背景音协调'},
            {'id': 'a_speech', 'observation': '口播内容：火车旅行'}],
            'criteria': [{'id': 'sound_clear', 'score': 4}, {'id': 'sound_voice', 'score': 3},
                         {'id': 'sound_background', 'score': 3}]}


def scores():
    return {'criteria': [{'id': key, 'score': 90, 'evidence': [
        {'source': 'visual', 'id': 'v1'}, {'source': 'visual', 'id': 'v2'},
        {'source': 'audio', 'id': 'a1'}, {'source': 'audio', 'id': 'a_speech'}]} for key in
        ('opening', 'content', 'visual_match', 'editing', 'subtitle', 'cta')]}


class PipelineTest(unittest.TestCase):
    def run_job(self, v=None, a=None, score=None):
        with patch.object(pipeline.full_frame_review, 'analyze_video', return_value=v or video()), \
             patch.object(pipeline, '_extract_audio', return_value=b'audio'), \
             patch.object(pipeline.full_frame_audio, 'analyze_audio', return_value=a or audio()), \
             patch.object(pipeline, '_score', return_value=score or scores()):
            return pipeline.analyze('/unused', 'key')

    def test_complete_analysis_passes(self):
        self.assertEqual(self.run_job()['verdict'], '通过')

    def test_unknown_risk_routes_to_review(self):
        v = video()
        v['frames'][1]['logo'] = 'unknown'
        self.assertEqual(self.run_job(v=v)['verdict'], '转人工')

    def test_partial_frame_job_routes_to_review(self):
        v = video()
        v['complete'] = False
        v['failed_frames'] = [2]
        self.assertEqual(self.run_job(v=v)['verdict'], '转人工')

    def test_failed_audio_cannot_produce_sound_score(self):
        result = self.run_job(a={'status': 'failed', 'observations': [], 'criteria': []})
        self.assertEqual(result['verdict'], '转人工')
        self.assertIsNone(result['scores']['sound'])


if __name__ == '__main__':
    unittest.main()
