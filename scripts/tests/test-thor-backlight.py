#!/usr/bin/env python3
"""Exercise Thor brightness arbitration without devices, mounts or services."""
from pathlib import Path
import runpy
import tempfile
import threading
import unittest
from unittest.mock import Mock, mock_open, patch

REPO = Path(__file__).resolve().parents[2]
MODULE = runpy.run_path(str(REPO / 'dualscreen-overlay/usr/lib/steamos-arm/bottom-screen/thor-backlightd'))
Daemon = MODULE['Daemon']
Panel = MODULE['Panel']
GLOBALS = Daemon.apply.__globals__


class FakePanel:
    def __init__(self, maximum, current):
        self.max = maximum
        self.current = self.last = current
        self.pending = False
        self.writes = []
        self.on = True

    def read(self):
        return self.current

    def write(self, value, force=False):
        value = max(0, min(self.max, value))
        if force or value != self.last:
            self.writes.append(value)
            self.current = self.last = value
            self.pending = False

    def power(self, on):
        self.on = on


class BacklightTests(unittest.TestCase):
    def setUp(self):
        self.mode = patch.dict(GLOBALS, game_mode=lambda: True)
        self.mode.start()
        self.addCleanup(self.mode.stop)
        self.d = Daemon.__new__(Daemon)
        self.d.lock = threading.Lock()
        self.d.top = FakePanel(1000, 500)
        self.d.bottom = FakePanel(65535, 32768)
        self.d.steam_max = 65535
        self.d.cfg = {'bottom_share': 50, 'bottom_on': False}
        self.d.value = 32768
        self.d.write_steam_file = Mock(side_effect=lambda value: setattr(self.d, 'value', value))
        self.d.steam_value = lambda: self.d.value

    def test_external_top_updates_bottom_share_and_power_without_echo(self):
        self.d.top.current = 250
        self.assertTrue(self.d.follow_top())
        self.assertEqual(self.d.value, 16384)
        self.d.apply()
        self.assertEqual(self.d.top.writes, [])
        self.assertEqual(self.d.bottom.last, round((16384 / 65535) ** (1 / 2.2) * .5 * 65535))
        self.assertFalse(self.d.bottom.on)
        self.assertFalse(self.d.follow_top())

    def test_desktop_ignores_top_and_keeps_raw_bottom_level(self):
        with patch.dict(GLOBALS, game_mode=lambda: False):
            self.d.top.current = 250
            self.assertFalse(self.d.follow_top())
            self.d.apply()
        self.assertEqual(self.d.bottom.last, 32768)
        self.assertEqual(self.d.top.writes, [])
        self.d.write_steam_file.assert_not_called()

    def test_unreadable_uninitialized_and_unchanged_top_are_ignored(self):
        for current, last in [(-1, 500), (250, -1), (500, 500)]:
            with self.subTest(current=current, last=last):
                self.d.top.current, self.d.top.last = current, last
                self.assertFalse(self.d.follow_top())
        self.d.write_steam_file.assert_not_called()

    def test_dashboard_write_is_not_reimported_as_external(self):
        self.d.value = 10000
        self.d.apply()
        self.assertFalse(self.d.follow_top())
        self.assertEqual(self.d.value, 10000)
        self.d.write_steam_file.assert_not_called()

    def test_dashboard_finishing_before_lock_cannot_be_overwritten_by_stale_read(self):
        d = self.d
        d.top.current = 250

        class DashboardFinishes:
            def __enter__(self):
                # Deterministic interleaving: a dashboard apply owns the lock
                # until this point and commits a newer level before releasing it.
                d.top.current = d.top.last = 800
                d.value = 52428

            def __exit__(self, *args):
                pass

        d.lock = DashboardFinishes()
        self.assertFalse(d.follow_top())
        self.assertEqual(d.value, 52428)
        self.assertEqual(d.top.last, 800)
        d.write_steam_file.assert_not_called()

    def test_apply_clamps_levels_and_shares_and_retries_pending_top(self):
        for value, share, top, bottom in [(-10, -20, 1, 1), (999999, 200, 1000, 65535)]:
            with self.subTest(value=value):
                self.d.value = value
                self.d.cfg['bottom_share'] = share
                self.d.top.pending = True
                self.d.apply(force=True, top=False)
                self.assertEqual(self.d.top.last, top)
                self.assertEqual(self.d.bottom.last, bottom)
                self.assertFalse(self.d.top.pending)

    def test_power_retries_but_logs_identical_failure_once_until_success(self):
        panel = Panel.__new__(Panel)
        panel.d = '/mock-panel'
        opened = mock_open()
        error = OSError(22, 'panel not ready')
        opened.return_value.write.side_effect = [error, error, None, error]
        logger = Mock()
        with patch.dict(GLOBALS, rd=lambda path: '0', log=logger), patch('builtins.open', opened):
            panel.power(False)
            panel.power(False)
            self.assertEqual(logger.call_count, 1)
            panel.power(False)
            panel.power(False)
        self.assertEqual(opened.return_value.write.call_count, 4)
        self.assertEqual(logger.call_count, 2)

    def test_proxy_rewrite_keeps_inode_and_removes_old_digits(self):
        with tempfile.TemporaryDirectory(prefix='thor-backlight-test-') as temp:
            path = Path(temp) / 'brightness'
            with patch.dict(GLOBALS, STEAM_FILE=str(path), mounted=lambda _: path.exists()), patch('os.chown'):
                Daemon.write_steam_file(self.d, 65535)
                inode = path.stat().st_ino
                Daemon.write_steam_file(self.d, 3)
            self.assertEqual(path.read_text(), '3\n')
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(path.stat().st_mode & 0o777, 0o664)
            self.assertFalse(Path(str(path) + '.tmp').exists())


if __name__ == '__main__':
    unittest.main()
