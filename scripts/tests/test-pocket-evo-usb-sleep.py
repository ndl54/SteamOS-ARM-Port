#!/usr/bin/env python3
"""Temporary sysfs + simulated bind/unbind only; no installed helper execution."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / 'sm8550-overlay/usr/lib/pocketevo/pocket-evo-usb-sleep'
loader = importlib.machinery.SourceFileLoader('evo_usb_sleep', str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
usb = importlib.util.module_from_spec(spec)
loader.exec_module(usb)
NAME = '0000:01:00.0'


class Recovery(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.hosts = usb.Hosts(self.root, self.root / 'state', lambda _: None)
        self.hosts.driver.mkdir(parents=True)
        self.hosts.devices.mkdir(parents=True)
        self.device = self.hosts.devices / NAME
        self.device.mkdir()
        self.bind()
        (self.root / 'class/block').mkdir(parents=True)
        (self.root / 'bus/usb/devices').mkdir(parents=True)
        self.calls = []
        self.fail = 0
        self.hosts.write = self.write

    def bind(self):
        (self.device / 'driver').symlink_to(self.hosts.driver)
        (self.hosts.driver / NAME).symlink_to(self.device)

    def write(self, action, name):
        self.calls.append((action, name))
        if self.fail:
            self.fail -= 1
            raise OSError('simulated sysfs error')
        if action == 'unbind':
            (self.device / 'driver').unlink()
            (self.hosts.driver / NAME).unlink()
        else:
            self.bind()

    def test_roundtrip_and_repeated_post(self):
        self.assertTrue(self.hosts.run('pre'))
        self.assertEqual(self.hosts.load(), {NAME})
        self.assertTrue(self.hosts.run('post'))
        self.assertTrue(self.hosts.run('post'))
        self.assertEqual(self.hosts.load(), set())
        self.assertEqual(self.calls, [('unbind', NAME), ('bind', NAME)])

    def test_repeated_pre_keeps_recovery_ownership(self):
        self.hosts.run('pre')
        self.hosts.run('pre')
        self.assertEqual(self.hosts.load(), {NAME})
        self.assertTrue(self.hosts.run('post'))
        self.assertTrue((self.device / 'driver').is_symlink())

    def test_retry_failed_bind_and_later_post(self):
        self.hosts.run('pre')
        self.fail = 3
        self.assertFalse(self.hosts.run('post'))
        self.assertEqual(self.hosts.load(), {NAME})
        self.assertTrue(self.hosts.run('post'))
        self.assertEqual(len(self.calls), 5)

    def test_transient_bind_retries_within_post(self):
        self.hosts.run('pre')
        self.fail = 2
        self.assertTrue(self.hosts.run('post'))
        self.assertEqual(len(self.calls), 4)

    def test_failed_unbind_does_not_rebind_an_already_bound_host(self):
        self.fail = 1
        self.assertFalse(self.hosts.run('pre'))
        self.assertTrue(self.hosts.run('post'))
        self.assertEqual(self.calls, [('unbind', NAME)])

    def test_never_binds_unowned_device(self):
        (self.device / 'driver').unlink()
        (self.hosts.driver / NAME).unlink()
        self.assertTrue(self.hosts.run('post'))
        self.assertTrue(self.hosts.run('pre'))
        self.assertEqual(self.calls, [])

    def test_missing_pci_keeps_pending_recovery(self):
        self.hosts.run('pre')
        self.device.rmdir()
        self.assertFalse(self.hosts.run('post'))
        self.assertEqual(self.hosts.load(), {NAME})
        self.assertEqual(self.calls, [('unbind', NAME)])

    def test_different_driver_is_not_stolen(self):
        self.hosts.run('pre')
        other = self.root / 'other-driver'
        other.mkdir()
        (self.device / 'driver').symlink_to(other)
        self.assertFalse(self.hosts.run('post'))
        self.assertEqual(self.hosts.load(), {NAME})
        self.assertEqual(self.calls, [('unbind', NAME)])

    def test_storage_blocks_unbind_without_mount_swap_or_holder_assumptions(self):
        disk = self.device / 'usb1/1-1/block/sda'
        disk.mkdir(parents=True)
        (self.root / 'class/block/sda').symlink_to(disk)
        self.assertTrue(self.hosts.run('pre'))
        self.assertEqual(self.calls, [])

    def test_usb_storage_before_block_enumeration(self):
        interface = self.device / 'usb1/1-1/1-1:1.0'
        interface.mkdir(parents=True)
        (interface / 'bInterfaceClass').write_text('08\n')
        (self.root / 'bus/usb/devices/1-1:1.0').symlink_to(interface)
        self.assertTrue(self.hosts.run('pre'))
        self.assertEqual(self.calls, [])

    def test_storage_scan_error_fails_closed(self):
        (self.root / 'class/block').rmdir()
        self.assertFalse(self.hosts.run('pre'))
        self.assertEqual(self.calls, [])

    def test_state_write_failure_never_detaches_host(self):
        with patch.object(self.hosts, 'save', side_effect=OSError('full')):
            self.assertFalse(self.hosts.run('pre'))
        self.assertEqual(self.calls, [])

    def test_corrupt_state_refuses_operations(self):
        self.hosts.state.write_text('../../bad\n')
        with self.assertRaises(ValueError):
            self.hosts.run('post')
        self.assertEqual(self.calls, [])

    def test_exact_board_gate_before_runtime_state_or_hardware(self):
        compatible = self.root / 'compatible'
        for board in (b'ayaneo,pocketevo-other', b'ayn,odin2', b'qcom,sm8650', b''):
            compatible.write_bytes(board + b'\0qcom,sm8550\0')
            with patch.object(usb, 'COMPATIBLE', compatible), \
                    patch.object(usb.sys, 'argv', ['helper', 'pre']), \
                    patch.object(usb, 'Hosts', side_effect=AssertionError('hardware')):
                self.assertEqual(usb.main(), 0)


if __name__ == '__main__':
    unittest.main()
