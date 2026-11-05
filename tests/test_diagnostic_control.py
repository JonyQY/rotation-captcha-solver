import json
from pathlib import Path
import tempfile
import threading
from time import sleep, time
import unittest
import uuid

from spincap.diagnostic_control import consume_one, control_lock, submit, write_json


class ControlTests(unittest.TestCase):
    def test_separate_client_calls_keep_one_worker_alive(self):
        with tempfile.TemporaryDirectory() as folder:
            stop = threading.Event()
            calls = []

            def handle(request):
                calls.append(request['action'])
                return {'type':'status','sequence':len(calls)}

            def worker():
                while not stop.is_set():
                    consume_one(folder, handle)
                    sleep(0.005)

            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertEqual(submit(folder,'status',timeout=2)['sequence'], 1)
                self.assertTrue(thread.is_alive())
                self.assertEqual(submit(folder,'status',timeout=2)['sequence'], 2)
            finally:
                stop.set()
                thread.join(timeout=2)
            self.assertEqual(calls, ['status','status'])

    def test_expired_command_does_not_trigger_browser_action(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            name = uuid.uuid4().hex+'.json'
            write_json(root/'requests'/name, {'action':'test_once','expires_at':time()-1})
            result = consume_one(root, lambda _: self.fail('Expired command executed'))
            self.assertEqual(result['error_type'], 'ExpiredCommand')

    def test_interrupted_or_completed_command_is_never_replayed(self):
        for marker in ('running','responses'):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                name = uuid.uuid4().hex+'.json'
                write_json(root/marker/name, {})
                write_json(root/'requests'/name, {'action':'test_once','expires_at':time()+2})
                consume_one(root, lambda _: self.fail('Duplicate command executed'))
                self.assertFalse((root/'requests'/name).exists())

    def test_only_one_worker_can_own_control_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with control_lock(folder):
                with self.assertRaises(OSError):
                    with control_lock(folder):
                        self.fail('Duplicate worker acquired lock')
            with control_lock(folder):
                pass


if __name__ == '__main__':
    unittest.main()
