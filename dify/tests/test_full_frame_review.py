import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('full_frame_review', Path(__file__).parents[1] / 'full_frame_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def response(batch, key, model, timeout):
    return {'frames': [{'frame': f['frame'], 'observation': '画面', 'face': 'absent',
                        'flag': 'absent', 'logo': 'present' if f['frame'] == 2 else 'absent'}
                       for f in batch]}, {'total_tokens': 10}


class FullFrameTests(unittest.TestCase):
    def test_every_frame_is_submitted_and_logo_retained(self):
        with patch.object(review, '_timestamps', return_value=[0, .04, .08]), \
             patch.object(review, '_decode_frames', return_value=iter([b'a', b'b', b'c'])), \
             patch.object(review, '_call_api', side_effect=response) as api:
            out = review.analyze_video('video', 'key', batch_size=2, retries=0)
        self.assertTrue(out['complete'])
        self.assertEqual((out['decoded_frames'], out['verified_frames']), (3, 3))
        self.assertEqual(api.call_count, 2)
        self.assertEqual(out['frames'][1]['logo'], 'present')
        self.assertEqual(out['frames'][2]['time_sec'], .08)

    def test_invalid_model_response_never_certifies_batch(self):
        with patch.object(review, '_timestamps', return_value=[0, .04]), \
             patch.object(review, '_decode_frames', return_value=iter([b'a', b'b'])), \
             patch.object(review, '_call_api', return_value=({'frames': []}, {})):
            out = review.analyze_video('video', 'key', retries=0)
        self.assertFalse(out['complete'])
        self.assertEqual(out['failed_frames'], [1, 2])

    def test_decoder_truncation_cannot_report_complete(self):
        with patch.object(review, '_timestamps', return_value=[0, .04]), \
             patch.object(review, '_decode_frames', return_value=iter([b'a'])), \
             patch.object(review, '_call_api', side_effect=response):
            out = review.analyze_video('video', 'key', retries=0)
        self.assertFalse(out['complete'])
        self.assertIn('帧数', out['error'])

    def test_unknown_risk_does_not_mark_complete(self):
        def unknown(batch, key, model, timeout):
            data, usage = response(batch, key, model, timeout)
            data['frames'][0]['flag'] = 'unknown'
            return data, usage
        with patch.object(review, '_timestamps', return_value=[0]), \
             patch.object(review, '_decode_frames', return_value=iter([b'a'])), \
             patch.object(review, '_call_api', side_effect=unknown):
            out = review.analyze_video('video', 'key', retries=0)
        self.assertFalse(out['complete'])
        self.assertEqual(out['unknown_frames'], [1])

    def test_request_size_splits_batches_without_dropping_frames(self):
        with patch.object(review, 'MAX_REQUEST_BYTES', 500), \
             patch.object(review, 'FRAME_OVERHEAD_BYTES', 32), \
             patch.object(review, '_timestamps', return_value=[0, .04, .08]), \
             patch.object(review, '_decode_frames', return_value=iter([b'a' * 180] * 3)), \
             patch.object(review, '_call_api', side_effect=response) as api:
            out = review.analyze_video('video', 'key', retries=0)
        self.assertTrue(out['complete'])
        self.assertEqual(out['verified_frames'], 3)
        self.assertEqual(api.call_count, 3)

    def test_oversized_single_frame_fails_closed(self):
        with patch.object(review, 'MAX_REQUEST_BYTES', 500), \
             patch.object(review, 'FRAME_OVERHEAD_BYTES', 32), \
             patch.object(review, '_timestamps', return_value=[0]), \
             patch.object(review, '_decode_frames', return_value=iter([b'a' * 400])), \
             patch.object(review, '_call_api') as api:
            out = review.analyze_video('video', 'key', retries=0)
        self.assertFalse(out['complete'])
        self.assertEqual(out['failed_frames'], [1])
        api.assert_not_called()

    def test_api_rejects_request_larger_than_limit(self):
        batch = [{'frame': 1, 'time_sec': 0, 'jpeg': b'a' * 100}]
        with patch.object(review, 'MAX_REQUEST_BYTES', 100), \
             patch.object(review.urllib.request, 'urlopen') as call:
            with self.assertRaises(ValueError):
                review._call_api(batch, 'key', 'model', 1)
        call.assert_not_called()

    def test_duplicate_frame_ids_are_rejected(self):
        batch = [{'frame': 1}, {'frame': 2}]
        row = {'frame': 1, 'observation': '画面', 'face': 'absent', 'flag': 'absent', 'logo': 'absent'}
        with self.assertRaises(ValueError):
            review._validate(batch, {'frames': [row, row]})


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), '需要 ffmpeg 和 ffprobe')
class RealVideoTests(unittest.TestCase):
    def check_real_video(self, path):
        timestamps = review._timestamps(str(path))
        with patch.object(review, '_call_api', side_effect=response):
            out = review.analyze_video(str(path), 'fake-key', retries=0)
        self.assertTrue(out['complete'], out.get('error'))
        self.assertEqual(out['decoded_frames'], len(timestamps))
        self.assertEqual(out['verified_frames'], len(timestamps))
        self.assertEqual([frame['time_sec'] for frame in out['frames']], timestamps)
        return timestamps

    def test_workspace_video(self):
        path = Path(__file__).resolve().parents[3] / '测试视频.mov'
        if not path.is_file():
            self.skipTest('测试视频不存在')
        self.assertTrue(self.check_real_video(path))

    def test_scaling_bounds_resolution_without_upscaling(self):
        with tempfile.TemporaryDirectory() as directory:
            for source, expected in [('640x360', (640, 360)), ('1920x1080', (1536, 864))]:
                path = str(Path(directory) / (source + '.mkv'))
                subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi',
                                '-i', 'testsrc=size=' + source + ':rate=1:duration=1',
                                '-frames:v', '1', path], check=True, timeout=60)
                jpeg = next(review._decode_frames(path))
                probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                        'stream=width,height', '-of', 'json', 'pipe:0'],
                                       input=jpeg, capture_output=True, check=True, timeout=60)
                stream = json.loads(probe.stdout)['streams'][0]
                self.assertEqual((stream['width'], stream['height']), expected)

    def test_variable_frame_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'variable.mkv')
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi',
                            '-i', 'testsrc=size=160x120:rate=30:duration=1',
                            '-vf', 'setpts=N*N/(30*TB)', '-fps_mode', 'vfr', path],
                           check=True, timeout=60)
            timestamps = self.check_real_video(path)
            gaps = {round(b - a, 3) for a, b in zip(timestamps, timestamps[1:])}
            self.assertGreater(len(gaps), 1)

if __name__ == '__main__':
    unittest.main()
