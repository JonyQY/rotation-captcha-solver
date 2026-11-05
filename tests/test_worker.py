import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spincap import AngleSession, CallableReader
from spincap.cli import main


def readers_for(predict):
    readers = []
    for tier in ('pico', 'nano', 'fast', 'max'):
        reader = CallableReader('rotation-' + tier, predict)
        reader.tier = tier
        readers.append(reader)
    return readers


class WorkerTests(unittest.TestCase):
    def test_session_loads_once_but_predicts_each_new_image(self):
        calls = []

        def predict(image):
            calls.append(image)
            return 90 if image == 'first' else 180

        with patch('spincap.api.default_readers', return_value=readers_for(predict)) as factory:
            session = AngleSession()
            self.assertEqual(session.read_angle('first'), 90)
            self.assertEqual(session.read_angle('second'), 180)
            factory.assert_called_once()
        self.assertEqual(calls, ['first'] * 4 + ['second'] * 4)

    def test_session_retains_baseline_failure_and_consensus_rejection(self):
        readers = readers_for(lambda image: 90)
        session = AngleSession(readers=readers)
        self.assertEqual(session.read_angle('first'), 90)
        readers[-1]._function = lambda image: None
        self.assertIsNone(session.read_angle('second'))
        readers[-1]._function = lambda image: 180
        self.assertIsNone(session.read_angle('third'))

    def test_worker_recovers_after_invalid_requests_and_reuses_models(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder).resolve() / 'image.png'
            image.write_bytes(b'fixture')
            requests = [
                '{broken',
                json.dumps({'image': str(image), 'pixels_per_turn': -1}),
                json.dumps({'image': str(image), 'complement': 'false'}),
                json.dumps({'id': 1, 'image': str(image), 'pixels_per_turn': 240,
                            'complement': True}),
                json.dumps({'id': 2, 'image': str(image)}),
            ]
            output = io.StringIO()
            with patch('spincap.api.default_readers', return_value=readers_for(lambda _: 90)) as factory, \
                    patch('sys.stdin', io.StringIO('\n'.join(requests) + '\n')), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(main(['--stdio']), 0)
                factory.assert_called_once()
            ready, *results = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(ready['type'], 'ready')
            self.assertEqual(len(results), 5)
            for result in results[:3]:
                self.assertFalse(result['usable'])
                self.assertIn('error', result)
                self.assertNotIn('offset_px', result)
            self.assertEqual(results[3]['id'], 1)
            self.assertEqual(results[3]['offset_px'], 180)
            self.assertTrue(results[4]['usable'])
            self.assertNotIn('offset_px', results[4])


if __name__ == '__main__':
    unittest.main()
