#!/usr/bin/env python3
"""Temporary-file/fake-RTC policy tests; never touch host power or sysfs."""
import json
import configparser
import fcntl
from pathlib import Path
import runpy
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / 'steamos-overlay/usr/lib/systemd/system-sleep/steamos-arm-low-battery'


class RTC:
    def __init__(self):
        self.value, self.writes, self.error = '', [], False

    def read_text(self):
        return self.value

    def write_text(self, text):
        if self.error:
            raise OSError('RTC write failed')
        self.writes.append(text.strip())
        if text.startswith('+'):
            if self.value not in ('', '0'):
                raise OSError('busy')
            # Deliberately different from the host wall clock.
            self.value = str(100000 + int(text))
        else:
            self.value = ''


class LowBattery(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.g = runpy.run_path(str(HOOK), run_name='low_battery_test')['run'].__globals__
        for name in ('SUPPLIES', 'BOOT', 'SUCCESS', 'STATE', 'LOCK', 'RATE'):
            self.g[name] = self.root / name
        self.g['SUPPLIES'].mkdir()
        self.g['BOOT'].write_text('boot-1')
        self.g['SUCCESS'].write_text('10')
        self.rtc = self.g['RTC'] = RTC()
        self.now = 10**12
        self.on_sleep = lambda: None
        self.g['time'] = SimpleNamespace(CLOCK_BOOTTIME=7,
            clock_gettime_ns=lambda _: self.now, sleep=lambda _: self.on_sleep())
        self.commands = Mock(return_value=SimpleNamespace(returncode=0))
        self.g['subprocess'] = SimpleNamespace(run=self.commands,
                                               TimeoutExpired=subprocess.TimeoutExpired)
        self.logs = []
        self.g['log'] = self.logs.append
        self.supply('BAT0', type='Battery', capacity='50', status='Discharging')
        self.supply('usb', type='USB', online='0')

    def supply(self, name, **values):
        directory = self.g['SUPPLIES'] / name
        directory.mkdir(exist_ok=True)
        for key, value in values.items():
            (directory / key).write_text(value)

    def hook(self, phase, action='suspend'):
        self.g['sys'] = SimpleNamespace(argv=['hook', phase, action])
        self.assertEqual(self.g['main'](), 0)

    def resume(self, cap='8', seconds=3600):
        self.now += seconds * 10**9
        self.supply('BAT0', capacity=cap)
        self.g['SUCCESS'].write_text('11')
        self.hook('post')

    def test_units_and_actual_rtc_readback(self):
        self.supply('BAT0', capacity='11')
        self.hook('pre')
        self.assertEqual(self.rtc.writes, ['+3600'])
        state = json.loads(self.g['STATE'].read_text())
        self.assertEqual(state['alarm'], 103600)

    def test_critical_sleep_checks_in_minute_not_fifteen(self):
        for cap in ('0', '4', '8'):
            self.supply('BAT0', capacity=cap)
            self.hook('pre')
            self.assertEqual(self.rtc.writes[-1], '+60')

    def test_foreign_and_replaced_alarms_preserved(self):
        self.rtc.value = '200000'
        self.hook('pre')
        self.assertEqual(self.rtc.writes, [])
        self.rtc.value = ''
        self.hook('pre')
        self.rtc.value = '300000'
        self.resume(cap='20')
        self.assertEqual(self.rtc.value, '300000')
        self.assertNotIn('0', self.rtc.writes)

    def test_consumed_once_and_nonblocking_shutdown(self):
        self.hook('pre')
        self.resume()
        self.commands.assert_called_once_with(['systemctl', '--no-block', 'poweroff'],
                                              timeout=10, check=False)
        self.assertFalse(self.g['STATE'].exists())
        self.hook('post')
        self.assertEqual(self.commands.call_count, 1)

    def test_never_resuspends_manual_or_alarm_wake(self):
        for seconds in (1, 86400):
            self.hook('pre')
            self.resume(cap='9', seconds=seconds)
        self.commands.assert_not_called()

    def test_charging_full_unknown_and_online_sources(self):
        for status in ('Charging', 'Full', 'Unknown', 'Not charging'):
            self.supply('BAT0', status=status)
            self.hook('pre')
        self.supply('BAT0', status='Discharging')
        for online in ('1', 'bad', ''):
            self.supply('usb', online=online)
            self.hook('pre')
        self.assertEqual(self.rtc.writes, [])

    def test_peripheral_battery_ignored_multiple_system_batteries_skipped(self):
        self.supply('A-controller', type='Battery', scope='Device', capacity='1', status='Discharging')
        self.hook('pre')
        self.assertEqual(json.loads(self.g['STATE'].read_text())['battery'], 'BAT0')
        self.supply('BAT1', type='Battery', capacity='90', status='Discharging')
        self.hook('pre')
        self.assertFalse(self.g['STATE'].exists())
        self.commands.assert_not_called()

    def test_device_scoped_online_usb_ignored(self):
        self.supply('pad', type='USB', scope='Device', online='1')
        self.hook('pre')
        self.assertTrue(self.g['STATE'].exists())

    def test_invalid_capacity_never_arithmetic_or_shutdown(self):
        for cap in ('', '-1', '101', '8.0', 'x', '９', '9'*100):
            self.supply('BAT0', capacity=cap)
            self.hook('pre')
        self.assertEqual(self.rtc.writes, [])
        self.commands.assert_not_called()

    def test_missing_battery_and_absent_battery(self):
        (self.g['SUPPLIES'] / 'BAT0/capacity').unlink()
        self.hook('pre')
        self.supply('BAT0', present='0')
        self.hook('pre')
        self.assertEqual(self.rtc.writes, [])

    def test_cleanup_even_after_battery_disappears(self):
        self.hook('pre')
        (self.g['SUPPLIES'] / 'BAT0/capacity').unlink()
        self.hook('post')
        self.assertEqual(self.rtc.value, '')
        self.assertFalse(self.g['STATE'].exists())

    def test_second_sample_cancels_on_charger_or_gauge_recovery(self):
        for changed in ('charger', 'capacity'):
            self.supply('usb', online='0')
            self.supply('BAT0', capacity='20')
            self.hook('pre')
            self.on_sleep = (lambda: self.supply('usb', online='1')) if changed == 'charger' else (
                lambda: self.supply('BAT0', capacity='9'))
            self.resume()
        self.commands.assert_not_called()

    def test_invalid_state_new_boot_and_unpaired_post(self):
        for state in ('junk', '[]', '{}'):
            self.g['STATE'].write_text(state)
            self.rtc.value = '100001'
            self.hook('post')
            self.assertEqual(self.rtc.value, '100001')
        self.rtc.value = ''
        self.hook('pre')
        self.g['BOOT'].write_text('boot-2')
        self.resume()
        self.commands.assert_not_called()

    def test_hibernation_modes_do_not_touch_alarm_or_state(self):
        self.rtc.value = '300000'
        self.g['STATE'].write_text('untouched')
        for action in ('hibernate', 'hybrid-sleep', 'suspend-then-hibernate', 'standby'):
            self.hook('pre', action)
            self.hook('post', action)
        self.assertEqual(self.rtc.writes, [])
        self.assertEqual(self.g['STATE'].read_text(), 'untouched')

    def test_rate_learning_boottime_and_bounds(self):
        self.hook('pre')
        self.resume(cap='40')
        self.assertEqual(json.loads(self.g['RATE'].read_text()), {'battery': 'BAT0', 'rate': 1000})
        self.hook('pre')
        self.assertEqual(self.rtc.writes[-1], '+11520')
        self.g['RATE'].write_text('{"battery":"BAT0","rate":99999999999}')
        self.assertEqual(self.g['rate_for']('BAT0'), 300)
        self.g['RATE'].write_text('99999999999999')
        self.assertEqual(self.g['rate_for']('BAT0'), 300)

    def test_no_learning_on_failed_suspend_or_charge_gain(self):
        self.hook('pre')
        self.now += 3600 * 10**9
        self.supply('BAT0', capacity='20')
        self.hook('post')
        self.assertFalse(self.g['RATE'].exists())
        self.hook('pre')
        self.resume(cap='80')
        self.assertFalse(self.g['RATE'].exists())

    def test_rtc_failure_and_shutdown_failure_are_logged(self):
        self.rtc.error = True
        self.hook('pre')
        self.assertTrue(any('unavailable' in log for log in self.logs))
        self.rtc.error = False
        self.hook('pre')
        self.commands.return_value.returncode = 1
        self.resume()
        self.assertTrue(any('request failed' in log for log in self.logs))

    def test_shutdown_timeout_does_not_block_hook_forever(self):
        self.hook('pre')
        self.commands.side_effect = subprocess.TimeoutExpired('systemctl', 10)
        self.resume()
        self.assertTrue(any('unavailable' in log for log in self.logs))

    def test_concurrent_hook_skips_without_touching_state(self):
        with self.g['LOCK'].open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.hook('pre')
        self.assertFalse(self.g['STATE'].exists())
        self.assertEqual(self.rtc.writes, [])

    def test_rate_save_failure_still_requests_shutdown(self):
        self.hook('pre')
        self.g['RATE'] = self.root / 'not-a-directory' / 'rate'
        (self.root / 'not-a-directory').write_text('file')
        self.resume()
        self.commands.assert_called_once()

    def test_alarm_write_race_does_not_clear_competing_owner(self):
        original = self.rtc.write_text
        def competing_write(text):
            self.rtc.value = '400000'
            original(text)
        self.rtc.write_text = competing_write
        self.hook('pre')
        self.assertEqual(self.rtc.value, '400000')
        self.assertEqual(json.loads(self.g['STATE'].read_text())['alarm'], 0)
        self.hook('post')
        self.assertEqual(self.rtc.value, '400000')


class Config(unittest.TestCase):
    def test_valid_low_preserved_invalid_low_repaired(self):
        configure = runpy.run_path(str(ROOT / 'scripts/configure-upower.py'))['configure']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'UPower.conf'
            for low, expected in (('20.0', '20.0'), ('6', '10'), ('nan', '10'), ('oops', '10')):
                path.write_text('[UPower]\nPercentageLow=' + low + '\n')
                configure(path)
                self.assertIn('PercentageLow=' + expected + '\n', path.read_text())

    def test_duplicate_configuration_fails_without_write(self):
        configure = runpy.run_path(str(ROOT / 'scripts/configure-upower.py'))['configure']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'UPower.conf'
            source = '[UPower]\nPercentageAction=2\nPercentageAction=3\n'
            path.write_text(source)
            with self.assertRaises(configparser.Error):
                configure(path)
            self.assertEqual(path.read_text(), source)

    def test_missing_commented_spaced_policy_and_idempotence(self):
        configure = runpy.run_path(str(ROOT / 'scripts/configure-upower.py'))['configure']
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'UPower.conf'
            for source in (None, '# config\n',
                           '[UPower]\n#PercentageAction=2\n PercentageCritical = 2\nUsePercentageForPolicy=false\nIgnoreLid=true\n[Other]\nKey=val\n'):
                if path.exists():
                    path.unlink()
                if source is not None:
                    path.write_text(source)
                configure(path)
                first = path.read_text()
                configure(path)
                self.assertEqual(path.read_text(), first)
                self.assertIn('UsePercentageForPolicy=true', first)
                self.assertIn('CriticalPowerAction=PowerOff', first)
                self.assertIn('PercentageLow=10', first)
                if source and 'IgnoreLid' in source:
                    self.assertIn('IgnoreLid=true', first)
                    self.assertIn('[Other]\nKey=val', first)


if __name__ == '__main__':
    unittest.main()
