#!/usr/bin/env python3
"""Common LED sleep ownership, using temporary files and real local flock only."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
COMMON = REPO / 'sm8650-overlay/usr/lib/konkr'
spec = importlib.util.spec_from_file_location('stick_sleep', COMMON / 'stick_sleep.py')
led = importlib.util.module_from_spec(spec)
spec.loader.exec_module(led)


class Sleep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in [('LEDS', self.root / 'leds'), ('RUNTIME', self.root / 'runtime'),
                            ('COMPATIBLE', self.root / 'compatible'), ('STANDBY', self.root / 'standby')]:
            p = patch.object(led, name, value)
            p.start()
            self.addCleanup(p.stop)
        led.LEDS.mkdir()
        led.COMPATIBLE.write_bytes(b'qcom,sm8650\0')

    def device(self, name, brightness='127', effect=None):
        d = led.LEDS / name
        d.mkdir()
        (d / 'brightness').write_text(brightness + '\n')
        if effect is not None:
            (d / 'effect').write_text(effect + '\n')
        (d / 'multi_intensity').write_text('1 2 3\n')
        return d

    def value(self, d, attr='brightness'):
        return (d / attr).read_text().strip()

    def test_all_stick_layouts_and_unrelated_leds(self):
        sticks = [self.device(n) for n in ('konkr:rgb:joysticks', 'left-joystick',
                  'right-joystick', 'rgb:l1', 'rgb:r4', 'rgb:l12')]
        other = [self.device(n) for n in ('power-led', 'rgb:l', 'rgb:l1x', 'keyboard')]
        led.change('pre')
        self.assertTrue(all(self.value(d) == '0' for d in sticks))
        self.assertTrue(all(self.value(d) == '127' for d in other))
        led.change('post')
        self.assertTrue(all(self.value(d) == '127' for d in sticks + other))
        self.assertTrue(all(self.value(d, 'multi_intensity') == '1 2 3' for d in sticks))

    def test_effect_restore_order_off_and_repeated_calls_without_daemon(self):
        d = self.device('konkr:rgb:joysticks', '0', 'breath 1 2 3')
        calls = []
        real = led.write
        def write(path, value):
            calls.append((path.name, value))
            real(path, value)
        with patch.object(led, 'write', write):
            led.change('pre')
            first = (led.RUNTIME / 'state.json').read_bytes()
            led.change('pre')
            self.assertEqual((led.RUNTIME / 'state.json').read_bytes(), first)
            self.assertEqual(calls[:2], [('brightness', '0'), ('effect', 'static')])
            led.change('post')
            self.assertEqual(calls[-2:], [('brightness', '0'), ('effect', 'breath 1 2 3')])
            count = len(calls)
            led.change('post')
            self.assertEqual(len(calls), count)
        self.assertEqual(self.value(d), '0')
        self.assertEqual(self.value(d, 'effect'), 'breath 1 2 3')

    def test_trigger_restored_and_busy_sleep_lock_does_not_stall_daemon(self):
        d = self.device('rgb:l1')
        (d / 'trigger').write_text('none [timer] heartbeat\n')
        led.change('pre')
        self.assertEqual(self.value(d, 'trigger'), 'none')
        led.change('post')
        self.assertEqual(self.value(d, 'trigger'), 'timer')
        class Writer:
            sticks = [str(d)]
            @led.awake_only
            def update(self):
                raise AssertionError('must not run while sleep owns lock')
        with led.locked():
            Writer().update()

    def test_snapshot_failure_does_not_blank(self):
        d = self.device('rgb:r1')
        with patch.object(Path, 'replace', side_effect=OSError('publish failure')):
            with self.assertRaises(OSError):
                led.change('pre')
        self.assertEqual(self.value(d), '127')
        self.assertFalse((led.RUNTIME / 'state.json').exists())

    def test_partial_errors_and_disappearance_do_not_block_other_restore(self):
        a, b = self.device('rgb:l1'), self.device('rgb:r1', '42')
        real = led.write
        def fail_a(path, value):
            if path.parent == a:
                raise OSError('injected LED I/O failure')
            real(path, value)
        with patch.object(led, 'write', fail_a):
            led.change('pre')
        self.assertEqual(self.value(b), '0')
        (a / 'brightness').unlink()
        led.change('post')
        self.assertFalse((a / 'brightness').exists())
        self.assertEqual(self.value(b), '42')
        self.assertFalse((led.RUNTIME / 'state.json').exists())

    def test_exact_evo_exclusion_before_runtime_or_led_access(self):
        d = self.device('rgb:l1')
        led.COMPATIBLE.write_bytes(b'ayaneo,pocketevo\0qcom,sm8550\0')
        led.change('pre')
        led.change('post')
        self.assertFalse(led.RUNTIME.exists())
        self.assertEqual(self.value(d), '127')
        for token in (b'ayaneo,pocketevo-plus\0', b'xayaneo,pocketevo\0'):
            led.COMPATIBLE.write_bytes(token)
            led.change('pre')
            self.assertEqual(self.value(d), '0')
            led.change('post')

    def test_corrupt_journal_cleanup_never_writes_arbitrary_paths(self):
        led.RUNTIME.mkdir()
        victim = self.root / 'victim'
        victim.write_text('keep')
        journal = led.RUNTIME / 'state.json'
        journal.write_text(json.dumps({'../../victim': {'brightness': '0'}}))
        with self.assertRaises(ValueError):
            led.change('post')
        self.assertEqual(victim.read_text(), 'keep')
        self.assertFalse(journal.exists())

    def test_actual_daemon_method_suppressed_then_latest_config_applies(self):
        text = (COMMON / 'konkrd').read_text()
        namespace = {'awake_only': led.awake_only, 'os': os,
                     'wr': lambda p, v: led.write(Path(p), str(v)),
                     'led_rgb': lambda d, rgb, b: led.write(Path(d) / 'brightness', str(b))}
        exec('from __future__ import annotations\n' + text[text.index('class Leds:'):text.index('\n\nRGB_PRESETS')], namespace)
        obj = namespace['Leds'].__new__(namespace['Leds'])
        d = self.device('konkr:rgb:joysticks')
        obj.sticks = [str(d)]
        obj.live_color = lambda mode: None
        cfg = {'rgb': {'mode': 'static', 'brightness': 31}}
        obj.apply_sticks(cfg)
        self.assertEqual(self.value(d), '31')
        led.change('pre')
        cfg['rgb']['brightness'] = 83
        obj.apply_sticks(cfg)  # HUP / live colour / profile paths use this method
        self.assertEqual(self.value(d), '0')
        self.assertTrue(obj.sticks_pending)
        led.change('post')
        self.assertEqual(self.value(d), '31')
        obj.apply_sticks(cfg)
        self.assertEqual(self.value(d), '83')
        self.assertFalse(obj.sticks_pending)
        led.STANDBY.touch()
        led.write(d / 'brightness', '0')
        obj.apply_sticks(cfg)
        self.assertEqual(self.value(d), '0')
        led.STANDBY.unlink()
        obj.apply_sticks(cfg)
        self.assertEqual(self.value(d), '83')

    def test_inflight_daemon_write_finishes_before_blank(self):
        d = self.device('rgb:l1')
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        class Writer:
            sticks = [str(d)]
            @led.awake_only
            def update(self):
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('test release timeout')
                led.write(d / 'brightness', '90')
        writer = threading.Thread(target=Writer().update)
        sleeper = threading.Thread(target=lambda: (led.change('pre'), finished.set()))
        writer.start()
        self.assertTrue(entered.wait(3))
        sleeper.start()
        self.assertFalse(finished.wait(0.05))
        release.set()
        writer.join(3)
        sleeper.join(3)
        self.assertTrue(finished.is_set())
        self.assertEqual(self.value(d), '0')
        led.change('post')
        self.assertEqual(self.value(d), '90')

    def test_real_pre_branches_blank_first_and_abort_cleanup_wiring(self):
        text = (COMMON / 'konkr-sleep').read_text()
        pre = text[text.index('pre() {'):text.index('\ntouch_devices()')]
        for light in ('true', 'false'):
            code = '''set -u
WIFI_MODS=(missing_test_module)
log() { :; }
lights_off() { echo blank; }
report_start() { echo report; }
wifi_mark() { :; }
xhci_off() { :; }
wake_sources() { :; }
audio() { :; }
touch_off() { :; }
ufs_off() { :; }
sync() { :; }
light() { LIGHT; }
'''.replace('LIGHT', light) + pre.replace('/sys/module/', str(self.root / 'modules') + '/') + '\npre\n'
            result = subprocess.run(['bash', '-c', code], text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.splitlines()[:2], ['blank', 'report'])
        unit = (REPO / 'sm8650-overlay/usr/lib/systemd/system/konkr-sleep.service').read_text()
        self.assertIn('ExecStopPost=/usr/bin/python3 /usr/lib/konkr/stick_sleep.py post', unit)
        self.assertIn('post() {\n  lights_on\n', text)


if __name__ == '__main__':
    unittest.main()
