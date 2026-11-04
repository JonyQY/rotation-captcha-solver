import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spincap import (CallableReader, GateConfig, build_solver, circular_distance,
                     decide, offset_for, read_angle)
from spincap.cli import main
from spincap.readers import local_model_dir, MODEL_FILES


class CoreTests(unittest.TestCase):
    def shard_fixture(self, folder):
        directory = Path(folder)
        filename = MODEL_FILES['max']
        data = b'example-model-binary-for-integrity-test'
        parts = [filename + '.part001', filename + '.part002']
        for name, content in zip(parts, (data[:12], data[12:])):
            (directory / name).write_bytes(content)
        (directory / 'manifest.json').write_text(json.dumps({'files': [{
            'name': filename, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'parts': parts}]}))
        return data, parts

    def test_model_parts_are_assembled_and_verified(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as cache:
            data, parts = self.shard_fixture(folder)
            with patch.dict('os.environ', {'SPINCAP_CACHE_DIR': cache}):
                path = local_model_dir('max', folder) / MODEL_FILES['max']
                self.assertEqual(path.read_bytes(), data)
                self.assertEqual(local_model_dir('max', folder), path.parent)

    def test_corrupted_model_part_never_reaches_inference(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as cache:
            data, parts = self.shard_fixture(folder)
            (Path(folder) / parts[0]).write_bytes(b'corrupt')
            with patch.dict('os.environ', {'SPINCAP_CACHE_DIR': cache}):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    local_model_dir('max', folder)

    def test_missing_weight_never_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                local_model_dir('max', folder)

    def test_lfs_pointer_is_rejected_with_recovery_instruction(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / MODEL_FILES['max']).write_text(
                'version https://git-lfs.github.com/spec/v1\noid sha256:example\nsize 300000000\n')
            with self.assertRaisesRegex(RuntimeError, 'git lfs pull'):
                local_model_dir('max', folder)

    def test_circular_wrap_and_offsets(self):
        self.assertEqual(circular_distance(359, 1), 2)
        self.assertEqual(offset_for(90, 240), 60)
        self.assertEqual(offset_for(90, 240, complement=True), 180)
        self.assertEqual(offset_for(270, 240, track_span=100), 100)

    def test_consensus_across_zero_and_seam_rejection(self):
        config = GateConfig(tiers=('a', 'b', 'ref'), baseline='ref')
        decision = decide({'a': 5, 'b': 355, 'ref': 350}, config)
        self.assertTrue(decision.usable)
        self.assertEqual(decision.angle, 350)
        self.assertFalse(decide({'a': 2, 'b': 359, 'ref': 1}, config).usable)

    def test_missing_explicit_baseline_never_falls_back(self):
        config = GateConfig(tiers=('a', 'b', 'ref'), baseline='ref', min_agreeing=1)
        self.assertFalse(decide({'a': 90, 'b': 91, 'ref': None}, config).usable)

    def test_invalid_and_unconfigured_votes_do_not_count(self):
        config = GateConfig(tiers=('a', 'b', 'ref'), baseline='ref')
        for invalid in (math.nan, math.inf, True, None):
            self.assertFalse(decide({'a': invalid, 'b': 90, 'ref': 90,
                                     'outsider': 90}, config).usable)

    def test_reader_names_and_baseline_are_validated(self):
        with self.assertRaises(ValueError):
            build_solver([CallableReader('a', lambda _: 90)] * 3)
        with self.assertRaises(ValueError):
            build_solver([CallableReader('a', lambda _: 90)], baseline='missing')

    @staticmethod
    def solver(values=(90, 91, 89), **kwargs):
        readers = [CallableReader(name, lambda _, v=v: v)
                   for name, v in zip(('ref', 'b', 'c'), values)]
        return build_solver(readers, baseline='ref', pixels_per_turn=240, **kwargs)

    def test_callbacks_are_composed_and_success_requires_verdict(self):
        offsets = []
        report = self.solver().solve(
            1, lambda: 'simulated', lambda: False,
            lambda px: offsets.append(px) or True, lambda: (True, 'success'))
        self.assertEqual(offsets, [60])
        self.assertEqual(report.summary()['passed'], 1)
        self.assertEqual(report.rounds[0].chosen_source, 'ref')

    def test_drag_failure_never_calls_verify(self):
        def verify():
            self.fail('verify must not run after drag failure')
        report = self.solver().solve(1, lambda: 'simulated', lambda: False,
                                     lambda _: False, verify)
        self.assertEqual(report.summary()['passed'], 0)
        self.assertEqual(report.summary()['submitted'], 0)
        self.assertEqual(report.rounds[0].outcome, 'drag-failed')

    def test_disagreement_stops_at_refresh_budget(self):
        refreshes = []
        def forbidden(*args):
            self.fail('No drag or verify without consensus')
        report = self.solver((90, 180, 270), max_refreshes=2).solve(
            1, lambda: 'simulated', lambda: refreshes.append(1) or True,
            forbidden, forbidden)
        self.assertEqual(len(refreshes), 2)
        self.assertEqual(report.rounds[0].outcome, 'no-consensus')
        self.assertEqual(report.summary()['submitted'], 0)

    def test_rejected_verdict_is_not_success(self):
        report = self.solver().solve(1, lambda: 'simulated', lambda: False,
                                     lambda _: True, lambda: (False, 'rejected'))
        self.assertEqual(report.summary()['submitted'], 1)
        self.assertEqual(report.summary()['passed'], 0)

    def test_read_angle_uses_max_even_when_not_first(self):
        readers = [CallableReader('rightwayup-'+name, lambda _, v=v: v)
                   for name, v in zip(('pico', 'nano', 'fast', 'max'), (170, 171, 169, 168))]
        for reader, tier in zip(readers, ('pico', 'nano', 'fast', 'max')):
            reader.tier = tier
        with patch('spincap.api.default_readers', return_value=readers):
            self.assertEqual(read_angle('simulated'), 168)

    def test_failed_single_reader_does_not_silently_switch_baseline(self):
        readers = [CallableReader('rightwayup-fast', lambda _: 90),
                   CallableReader('rightwayup-max', lambda _: None)]
        with patch('spincap.api.default_readers', return_value=readers):
            self.assertIsNone(read_angle('simulated', tiers=('fast','max'),
                                         require_agreement=False))

    def test_cli_json_and_no_consensus_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'input.png'
            image.write_bytes(b'simulated-input')
            for angle, expected_exit in ((90.0, 0), (None, 2)):
                output = io.StringIO()
                with patch('spincap.cli.read_angle', return_value=angle), contextlib.redirect_stdout(output):
                    code = main([str(image), '--pixels-per-turn', '240', '--complement'])
                result = json.loads(output.getvalue())
                self.assertEqual(code, expected_exit)
                self.assertEqual(result['usable'], angle is not None)
                if angle is not None:
                    self.assertEqual(result['offset_px'], 180)


if __name__ == '__main__':
    unittest.main()
