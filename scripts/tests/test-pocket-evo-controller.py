#!/usr/bin/env python3
"""Exercise the real UART transport on a PTY, without touching a device."""
from pathlib import Path
import importlib.machinery
import importlib.util
import os
import pty
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / 'sm8550-overlay/usr/lib/pocketevo'
sys.path.insert(0, str(HELPERS))
loader = importlib.machinery.SourceFileLoader('controller', str(HELPERS / 'pocket-evo-controller'))
spec = importlib.util.spec_from_loader(loader.name, loader)
controller = importlib.util.module_from_spec(spec)
loader.exec_module(controller)


class ControllerTest(unittest.TestCase):
    def test_existing_modes_never_open_uart(self):
        with tempfile.TemporaryDirectory() as directory:
            usb = Path(directory)
            device = usb / '1-1'
            device.mkdir()
            for vendor, product in [('045e', '028e'), ('4001', '0428')]:
                (device / 'idVendor').write_text(vendor + '\n')
                (device / 'idProduct').write_text(product + '\n')
                self.assertFalse(controller.recover(object(), usb))

    def test_missing_pad_sends_both_complete_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            master, slave = pty.openpty()
            try:
                link = controller.SerialLink(os.ttyname(slave), Path(directory) / 'serial.lock')
                delays = []
                self.assertTrue(controller.recover(link, Path(directory), delays.append))
                self.assertEqual(os.read(master, 1024), bytes.fromhex('e755050100000000005bed') + b'5505010000000000')
                self.assertEqual(delays, [0.1, 0.1])
            finally:
                os.close(master)
                os.close(slave)

    def test_unrelated_usb_does_not_suppress_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            device = Path(directory) / '1-1'
            device.mkdir()
            (device / 'idVendor').write_text('1c4f')
            (device / 'idProduct').write_text('0002')
            self.assertFalse(controller.has_gamepad(Path(directory)))

    def test_uart_lock_prevents_interleaving(self):
        with tempfile.TemporaryDirectory() as directory:
            master, slave = pty.openpty()
            try:
                lock = Path(directory) / 'serial.lock'
                owner = controller.SerialLink(os.ttyname(slave), lock)
                recovery = controller.SerialLink(os.ttyname(slave), lock, timeout=0.02)
                with owner.opened():
                    with self.assertRaises(TimeoutError):
                        controller.recover(recovery, Path(directory))
            finally:
                os.close(master)
                os.close(slave)


if __name__ == '__main__':
    unittest.main()
