import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('full_frame_audio', Path(__file__).resolve().parents[1] / 'full_frame_audio.py')
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


def response(rows, speech=None):
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps({'criteria': rows, 'speech': speech or {
            'status': 'present', 'content': 'Hello', 'evidence': '听到旁白 Hello'}}, ensure_ascii=False)}]}]}


def rows():
    return [{'id': 'sound_clear', 'score': 4, 'evidence': '第5秒旁白清楚', 'suggestion': ''},
            {'id': 'sound_voice', 'score': 1.5, 'evidence': '第8秒语速偏快', 'suggestion': '放慢语速'},
            {'id': 'sound_background', 'score': None, 'evidence': '', 'suggestion': ''}]


class AudioTest(unittest.TestCase):
    def test_complete_audio_is_sent_in_audio_input(self):
        request = audio.build_request(b'whole track')
        self.assertEqual(request['model'], 'qwen3.8-omni-flash')
        data = request['input'][0]['content'][1]
        self.assertEqual(data['type'], 'input_audio')
        self.assertEqual(data['data'], 'data:audio/mpeg;base64,d2hvbGUgdHJhY2s=')
        self.assertEqual(data['format'], 'mp3')

    def test_results_keep_evidence_and_unknown(self):
        out = audio.parse_response(response(rows()))
        self.assertEqual(out['status'], 'ok')
        self.assertEqual(out['observations'][0], {'id': 'a1', 'observation': '第5秒旁白清楚'})
        self.assertIsNone(out['criteria'][2]['score'])
        self.assertIn('Hello', out['observations'][-1]['observation'])

    def test_no_speech_and_uncertain_speech(self):
        absent = audio.parse_response(response(rows(), {'status': 'absent', 'content': '', 'evidence': '只有音乐'}))
        self.assertIn('未听到口播', absent['observations'][-1]['observation'])
        unknown = audio.parse_response(response(rows(), {'status': 'unknown', 'content': '', 'evidence': '听不清'}))
        self.assertNotIn('a_speech', [r['id'] for r in unknown['observations']])
        with self.assertRaises(ValueError):
            audio.parse_response(response(rows(), {'status': 'present', 'content': '', 'evidence': ''}))

    def test_rejects_duplicate_invalid_and_unsubstantiated_scores(self):
        variants = []
        duplicate = rows(); duplicate[1]['id'] = 'sound_clear'; variants.append(duplicate)
        invalid = rows(); invalid[0]['score'] = 3; variants.append(invalid)
        missing_evidence = rows(); missing_evidence[0]['evidence'] = ''; variants.append(missing_evidence)
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                audio.parse_response(response(variant))

    def test_model_failure_never_creates_scores(self):
        with patch.object(audio, 'urlopen', side_effect=TimeoutError):
            out = audio.analyze_audio(b'track', 'test-key')
        self.assertEqual(out['status'], 'failed')
        self.assertEqual(out['criteria'], [])
        self.assertNotIn('test-key', str(out))

    def test_rejects_empty_and_oversized_audio(self):
        with self.assertRaises(ValueError):
            audio.build_request(b'')
        with patch.object(audio, 'MAX_DATA_URI_BYTES', 30), self.assertRaises(ValueError):
            audio.build_request(b'a' * 20)


if __name__ == '__main__':
    unittest.main()
