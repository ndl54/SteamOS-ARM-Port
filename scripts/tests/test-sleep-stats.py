#!/usr/bin/env python3
"""Sleep diagnostics only: ordinary temporary files, fake clock and log sink."""
import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'steamos-overlay/usr/lib/systemd/system-sleep/steamos-arm-sleep-stats'


class SleepStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        module = runpy.run_path(str(HELPER), run_name='test_sleep_stats')
        self.g = module['run'].__globals__
        for key in ('STATS', 'STATE', 'BOOT_ID', 'WAKE_IRQ', 'INTERRUPTS'):
            self.g[key] = self.root / key
        self.g['STATS'].mkdir()
        self.g['BOOT_ID'].write_text('test-boot')
        self.g['WAKE_IRQ'].write_text('42')
        self.g['INTERRUPTS'].write_text('42: 0 1 test power-key\n')
        self.now = 1_000_000_000
        self.g['time'] = SimpleNamespace(CLOCK_BOOTTIME=7,
                                        clock_gettime_ns=lambda clock: self.now)
        self.logs = []
        self.g['log'] = self.logs.append
        self.sample(2, 2**63 + 5)

    def sample(self, count, ticks, name='cxsd'):
        (self.g['STATS'] / name).write_text(
            f'Count: {count}\nLast Entered At: 12\nLast Exited At: 13\n'
            f'Accumulated Duration: {ticks}\n')

    def run_hook(self, phase, action='suspend'):
        self.g['sys'] = SimpleNamespace(argv=['sleep-stats', phase, action])
        self.assertEqual(self.g['main'](), 0)

    def test_paired_unsigned_delta_and_consume_once(self):
        self.run_hook('pre')
        self.sample(5, 2**63 + 20)
        self.now += 5_500_000_000
        self.run_hook('post')
        self.assertIn('hook interval 5.500s', self.logs[-1])
        self.assertIn('cxsd:count+3,ticks+15', self.logs[-1])
        self.assertIn('last wake IRQ 42 power-key', self.logs[-1])
        self.assertNotIn('slept', self.logs[-1])
        self.assertFalse(self.g['STATE'].exists())
        old = list(self.logs)
        self.run_hook('post')
        self.assertEqual(self.logs, old)

    def test_reset_or_rollover_never_fabricates_delta(self):
        for old, new in (([2**32-1, 100], [0, 101]),
                         ([10, 2**64-1], [11, 0]), ([20, 200], [1, 5])):
            with self.subTest(old=old):
                self.assertEqual(self.g['delta']({'cxsd': old}, {'cxsd': new}),
                                 'cxsd:reset-or-wrap')

    def test_malformed_missing_duplicate_out_of_range_counters(self):
        for text in ('Count: -1\nAccumulated Duration: 1\n',
                     'Count: 1\n', 'Count: 1\nCount: 2\nAccumulated Duration: 2\n',
                     f'Count: {2**32}\nAccumulated Duration: 2\n',
                     f'Count: 1\nAccumulated Duration: {2**64}\n',
                     'Count: nope\nAccumulated Duration: 2\n'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    self.g['counters'](text)
        (self.g['STATS'] / 'cxsd').write_text('unavailable')
        self.run_hook('pre')
        self.assertFalse(self.g['STATE'].exists())
        self.assertIn('no valid pre counters', self.logs[-1])

    def test_only_passive_files_are_read_once(self):
        (self.g['STATS'] / 'ddr_stats').write_text('must never be opened')
        (self.g['STATS'] / 'unknown').write_text('must never be opened')
        (self.g['STATS'] / 'adsp').symlink_to(self.g['STATS'] / 'cxsd')
        original = Path.read_text
        reads = []
        def read(path, *args, **kwargs):
            reads.append(path.name)
            if path.name in ('ddr_stats', 'unknown', 'adsp'):
                raise AssertionError('unsafe diagnostic read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            values, missing = self.g['snapshot']()
        self.assertEqual(values, {'cxsd': [2, 2**63 + 5]})
        self.assertEqual(reads.count('cxsd'), 1)
        self.assertEqual(missing, ['adsp'])

    def test_missing_debugfs_invalidates_old_sample_without_mount(self):
        self.run_hook('pre')
        (self.g['STATS'] / 'cxsd').unlink()
        self.g['STATS'].rmdir()
        self.run_hook('pre')
        self.assertFalse(self.g['STATE'].exists())
        self.assertFalse(self.g['STATS'].exists())
        self.assertIn('unavailable', self.logs[-1])

    def test_repeated_pre_replaces_interval(self):
        self.run_hook('pre')
        self.sample(3, 2**63 + 8)
        self.now += 10_000_000_000
        self.run_hook('pre')
        self.sample(4, 2**63 + 9)
        self.now += 1_000_000_000
        self.run_hook('post')
        self.assertIn('interval 1.000s: cxsd:count+1,ticks+1', self.logs[-1])

    def test_atomic_failure_cannot_reuse_prior_state(self):
        self.run_hook('pre')
        with patch.object(self.g['os'], 'replace', side_effect=OSError('disk failure')):
            self.run_hook('pre')
        self.assertFalse(self.g['STATE'].exists())
        self.assertEqual(list(self.root.glob('.sleep-stats-*')), [])
        self.assertIn('disk failure', self.logs[-1])

    def test_boot_action_and_clock_mismatch(self):
        self.run_hook('pre')
        self.run_hook('post', 'hibernate')
        self.assertIn('unpaired', self.logs[-1])
        self.run_hook('pre')
        self.g['BOOT_ID'].write_text('different-boot')
        self.run_hook('post')
        self.assertIn('unpaired', self.logs[-1])
        self.run_hook('pre')
        self.now = 0
        self.run_hook('post')
        self.assertIn('invalid boottime', self.logs[-1])

    def test_corrupt_state_and_permission_failure_are_diagnostic_only(self):
        for raw in ('{broken', '[]', '{"start": -1, "values": {}}',
                    json.dumps({'start': 1, 'values': {'cxsd': []}}),
                    json.dumps({'start': 1, 'values': {'cxsd': [-1, 0]}})):
            self.g['STATE'].write_text(raw)
            self.run_hook('post')
            self.assertFalse(self.g['STATE'].exists())
            self.assertIn('diagnostics unavailable', self.logs[-1])
        original = Path.read_text
        def read(path, *a, **kw):
            if path.name == 'cxsd':
                raise PermissionError('denied')
            return original(path, *a, **kw)
        with patch.object(Path, 'read_text', read):
            self.run_hook('pre')
        self.assertFalse(self.g['STATE'].exists())

    def test_unpaired_counters_and_zero_irq_are_not_success_claims(self):
        self.run_hook('pre')
        (self.g['STATS'] / 'cxsd').unlink()
        self.sample(1, 9, 'ddr')
        self.g['WAKE_IRQ'].write_text('0')
        self.run_hook('post')
        self.assertIn('cxsd:unpaired ddr:unpaired', self.logs[-1])
        self.assertIn('last wake IRQ ?', self.logs[-1])

    def test_unknown_phase_has_no_effect(self):
        self.run_hook('pre')
        before = self.g['STATE'].read_bytes()
        self.run_hook('other')
        self.assertEqual(self.g['STATE'].read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
