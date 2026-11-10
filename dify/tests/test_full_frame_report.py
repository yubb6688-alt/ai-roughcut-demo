import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('full_frame_report', Path(__file__).parents[1] / 'full_frame_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class FullFrameReportTest(unittest.TestCase):
    def setUp(self):
        self.coverage = {'status': 'ok', 'total_frames': 2, 'checked_frames': [1, 2], 'failed_frames': []}
        self.visual = {'status': 'ok', 'risks': [], 'observations': [
            {'id': 'v1', 'frame': 1, 'time_sec': 0, 'observation': '开头画面'},
            {'id': 'v2', 'frame': 2, 'time_sec': 1, 'observation': '结尾画面'}]}
        self.audio = {'status': 'ok', 'source': 'audio_analysis', 'observations': [
            {'id': 'a1', 'observation': '语音清晰'}, {'id': 'a_speech', 'observation': '口播：火车旅行'}]}
        self.scores = {'criteria': [{'id': k, 'score': 80, 'evidence': [
            {'source': 'visual', 'id': 'v1'}, {'source': 'visual', 'id': 'v2'},
            {'source': 'audio', 'id': 'a1'}, {'source': 'audio', 'id': 'a_speech'}]} for k, _ in report.RUBRIC]}

    def run_report(self):
        return report.main(self.coverage, self.visual, self.audio, self.scores)

    def test_all_frames_and_evidence_pass_at_threshold(self):
        result = self.run_report()
        self.assertEqual(result['verdict'], '通过')
        self.assertEqual(result['total'], 80)

    def test_low_score_and_logo_each_trigger_review(self):
        self.scores['criteria'][0]['score'] = 79
        self.assertEqual(self.run_report()['verdict'], '转人工')
        self.scores['criteria'][0]['score'] = 80
        self.visual['risks'] = [{'type': 'logo', 'frame': 2, 'description': '品牌标识'}]
        self.assertEqual(self.run_report()['verdict'], '转人工')

    def test_missing_or_duplicate_frames_cannot_pass(self):
        for checked in ([1], [1, 1], [1, True]):
            self.coverage['checked_frames'] = checked
            self.assertFalse(self.run_report()['coverage_complete'])
            self.assertEqual(self.run_report()['verdict'], '转人工')

    def test_transcript_alone_cannot_score_sound(self):
        self.audio['source'] = 'transcript'
        result = self.run_report()
        self.assertIsNone(result['scores']['sound'])
        self.assertEqual(result['verdict'], '转人工')

    def test_malformed_risk_and_evidence_fail_closed(self):
        self.visual['risks'] = [{'type': [], 'frame': 1, 'description': 'x'}]
        self.assertEqual(self.run_report()['verdict'], '转人工')
        self.visual['risks'] = []
        self.scores['criteria'][0]['evidence'] = [{'source': 'visual', 'id': []}]
        self.assertEqual(self.run_report()['verdict'], '转人工')


if __name__ == '__main__':
    unittest.main()
