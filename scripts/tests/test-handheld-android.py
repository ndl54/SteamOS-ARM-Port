#!/usr/bin/env python3
"""080: Decky routing with fake DT, helpers and reboot; no device calls."""
import asyncio
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / 'external-and-mods/Decky/sm8650/konkr-control/main.py'


class Android(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('android080', PLUGIN)
        self.m = m = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, decky=types.SimpleNamespace()), patch('os.path.exists', return_value=False):
            spec.loader.exec_module(m)
        self.compat = b'ayaneo,pocketevo\0qcom,sm8550\0'
        def fake_open(path, *args, **kwargs):
            self.assertEqual(path, '/sys/firmware/devicetree/base/compatible')
            return io.BytesIO(self.compat)
        m.open = fake_open
        m.os = types.SimpleNamespace(geteuid=lambda: 0, path=types.SimpleNamespace(exists=lambda p: False, isdir=lambda p: False))
        self.run = Mock(return_value=types.SimpleNamespace(returncode=0))
        m.subprocess = types.SimpleNamespace(run=self.run, TimeoutExpired=subprocess.TimeoutExpired)
        self.plugin = m.Plugin()

    def boot(self):
        return asyncio.run(self.plugin.boot_android())

    def test_all_supported_boards_and_exact_soc(self):
        for soc, boards in self.m.HANDHELD_BOARDS.items():
            for board in boards:
                with self.subTest(board=board):
                    self.compat = (board + '\0' + soc + '\0').encode()
                    self.assertTrue(self.m.dualboot())
                    self.assertTrue(self.boot())
                    self.assertEqual(self.run.call_args.args[0],
                        ['systemctl', '--no-block', '--no-ask-password', 'reboot', '--reboot-argument=bootloader'])
                    self.assertEqual(self.run.call_args.kwargs, {'timeout': 10})
                    self.compat = (board + '\0qcom,unknown\0').encode()
                    self.assertFalse(self.m.dualboot())
        self.assertEqual(self.run.call_count, 23)

    def test_unknown_missing_lookalike_and_ambiguous_identity_never_reboot(self):
        for compat in (b'', b'qcom,sm8550\0', b'ayaneo,pocketevo-other\0qcom,sm8550\0',
                       b'ayaneo,pocketevo\0qcom,sm8650\0',
                       b'ayaneo,pocketevo\0ayn,odin2\0qcom,sm8550\0',
                       b'lenovo,unknown\0ayaneo,pocketevo\0qcom,sm8550\0'):
            self.compat = compat
            self.assertFalse(self.m.dualboot())
            self.assertFalse(self.boot())
        self.m.open = Mock(side_effect=FileNotFoundError('fake DT missing'))
        self.assertFalse(self.boot())
        self.run.assert_not_called()

    def test_nonroot_and_stale_capability_never_reboot(self):
        self.assertTrue(self.m.dualboot())
        self.compat = b'unknown\0'
        self.assertFalse(self.boot())
        self.compat = b'ayaneo,pocketevo\0qcom,sm8550\0'
        self.m.os.geteuid = lambda: 1000
        self.assertFalse(self.boot())
        self.run.assert_not_called()

    def test_reboot_failure_missing_permission_timeout(self):
        self.run.return_value.returncode = 1
        self.assertFalse(self.boot())
        for error in (FileNotFoundError('fake'), PermissionError('fake'), subprocess.TimeoutExpired('fake-systemctl', 10)):
            self.run.side_effect = error
            self.assertFalse(self.boot())

    def test_tablet_helpers_recheck_and_propagate_failure(self):
        for board, commands in (
            ('lenovo,elden', [['/usr/lib/steamos-arm/tablet-slot', 'check'], ['/usr/lib/steamos-arm/tablet-slot', 'android']]),
            ('lenovo,baldur', [['/usr/lib/steamos-arm/gen5-android', '--check'], ['/usr/lib/steamos-arm/gen5-android']])):
            self.compat = (board + '\0').encode()
            self.run.reset_mock()
            self.assertTrue(self.boot())
            self.assertEqual([c.args[0] for c in self.run.call_args_list], commands)
            self.assertEqual(self.run.call_args.kwargs, {})  # don't kill storage writes
            self.run.return_value.returncode = 1
            self.run.reset_mock()
            self.assertFalse(self.boot())
            self.assertEqual(self.run.call_count, 1)
            self.run.return_value.returncode = 0
        self.run.side_effect = subprocess.TimeoutExpired('fake-check', 8)
        self.assertFalse(self.boot())
        self.run.side_effect = [types.SimpleNamespace(returncode=0), types.SimpleNamespace(returncode=1)]
        self.assertFalse(self.boot())
        # Gen3 remains helper-rejected; it must never fall through to handheld reboot.
        self.compat = b'lenovo,tb321fu\0qcom,sm8650\0'
        self.run.side_effect = None
        self.run.return_value.returncode = 1
        self.run.reset_mock()
        self.assertFalse(self.boot())
        self.assertEqual(self.run.call_args.args[0], ['/usr/lib/steamos-arm/tablet-slot', 'check'])

    def test_state_labels_capability_and_menu_explanation(self):
        m = self.m
        m.load = lambda: dict(profile='balanced', rgb={}, fan={}, power_led=True, menu_clicks=True, buttons={})
        m.rd = lambda *a: ''
        m.glob = types.SimpleNamespace(glob=lambda p: [])
        m.evo_rgb_supported = lambda: False
        m.game_fan_state = lambda st: {}
        m.bypass_state = m.telemetry = lambda: {}
        for board, soc, label in [('ayaneo,pocketevo', 'qcom,sm8550', 'Android'),
                                  ('lenovo,elden', 'qcom,sm8750', 'ZUXOS'),
                                  ('lenovo,baldur', 'qcom,kaanapali', 'ZUI')]:
            self.compat = (board + '\0' + soc + '\0').encode()
            st = asyncio.run(self.plugin.get_state())
            self.assertTrue(st['has_dualboot'])
            self.assertEqual(st['dualboot_label'], 'Restart into ' + label)
            self.assertIn(label, st['dualboot_text'])
            if label == 'Android':
                self.assertIn('Requires ROCKNIX ABL', st['dualboot_text'])
                self.assertIn('boot menu', st['dualboot_text'])
        self.compat = b'unknown\0'
        self.assertFalse(asyncio.run(self.plugin.get_state())['has_dualboot'])


if __name__ == '__main__':
    unittest.main()
