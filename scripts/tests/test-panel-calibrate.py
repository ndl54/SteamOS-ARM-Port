#!/usr/bin/env python3
"""Calibration regressions using fake DRM replies and temporary files only.

No real device/sysfs access, services, builds or compiler invocation.
"""
import ctypes
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from unittest.mock import patch

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[2] / 'steamos-overlay/usr/lib/steamos-arm/panel-calibrate'
loader = importlib.machinery.SourceFileLoader('panel_calibrate', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
pc = importlib.util.module_from_spec(spec)
loader.exec_module(pc)
RP6 = 'retroidpocket,rp6'
ODIN = 'ayn,odin3'


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(pc, 'SAVED', str(self.tmp / 'saved.json')))
        self.stack.enter_context(patch.object(pc, 'LOCK', str(self.tmp / 'lock')))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.errors = self.stack.enter_context(redirect_stderr(io.StringIO()))

    def test_exact_board_and_panel_gating(self):
        for compat, expected in [('ayaneo,pocketevo', None), ('retroidpocket,rpnova', None),
                                 (RP6, RP6), (ODIN, ODIN)]:
            with self.subTest(compat=compat), patch.object(pc, 'compatible', return_value=[compat, 'qcom,sm8550']):
                self.assertEqual(pc.board(), expected)
        dev = self.tmp / 'panel'
        (dev / 'of_node').mkdir(parents=True)
        (dev / 'frame_len_120').touch()
        with patch.object(pc.glob, 'glob', return_value=[str(dev / 'frame_len_60')]):
            (dev / 'of_node/compatible').write_bytes(b'ayaneo,pocketevo-panel\0chipone,icna3512\0')
            self.assertIsNone(pc.panel(RP6))
            (dev / 'of_node/compatible').write_bytes(b'vtdr6130,rp6\0')
            self.assertEqual(pc.panel(RP6), str(dev))
            self.assertIsNone(pc.panel(ODIN))

    def test_saved_values_roundtrip_and_identity(self):
        values = {'frame_len_60': 2001, 'frame_len_120': 29}
        pc.save(RP6, values)
        self.assertEqual(pc.load(RP6), values)
        with self.assertRaises(ValueError):
            pc.load(ODIN)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ['saved.json'])

    def test_invalid_records_cannot_reach_writes(self):
        records = [[], None, {'frame_len_60': 2001}]
        for values in [{'../enable': 1}, {'frame_len_60': True}, {'frame_len_60': '2000'},
                       {'frame_len_120': 129}, {'frame_len_60': 1899}, {'frame_len_60': None}]:
            records.append({'board': RP6, 'panel': 'vtdr6130,rp6', 'values': values})
        for record in records:
            with self.subTest(record=record):
                Path(pc.SAVED).write_text(json.dumps(record))
                with patch.object(pc, 'board', return_value=RP6), patch.object(pc, 'write_attr') as write:
                    with self.assertRaises(ValueError):
                        pc.apply()
                    write.assert_not_called()

    def test_unreadable_saved_file_is_not_silently_replaced(self):
        with patch('builtins.open', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                pc.load(RP6)

    def test_sequences_count_missed_frames_and_wrap(self):
        for stamps in [[(10, 1000000), (13, 1050000), (16, 1100000)],
                       [(0xFFFFFFFE, 1000000), (1, 1050000), (4, 1100000)]]:
            with self.subTest(stamps=stamps), patch.object(pc, 'wait_vblank', side_effect=stamps), \
                 patch.object(pc.time, 'monotonic', side_effect=[0, 0.01, 0.05, 0.11]):
                self.assertAlmostEqual(pc.measure(7, 1, .1), 60)

    def test_invalid_timestamps_and_sequences_fail(self):
        for last in [(10, 1050000), (11, 1000000), (9, 1050000)]:
            with self.subTest(last=last), patch.object(pc, 'wait_vblank', side_effect=[(10, 1000000), last]), \
                 patch.object(pc.time, 'monotonic', return_value=0):
                with self.assertRaises(OSError):
                    pc.measure(7, 1)

    def test_vblank_ioctl_encoding_and_reply(self):
        def fake(fd, request, buf):
            self.assertEqual((fd, request, len(buf)), (7, 0xC018643A, 24))
            self.assertEqual(struct.unpack('=IIqq', buf), (7, 1, 0, 0))
            buf[:] = struct.pack('=IIqq', 7, 123, 5, 12345)
        with patch.object(pc.fcntl, 'ioctl', side_effect=fake):
            self.assertEqual(pc.wait_vblank(7, 3), (123, 5012345))

    def display_setup(self, *, rate=120, connection=1, crtc=44, resource_changed=False):
        self.stack.enter_context(patch.object(pc.glob, 'glob', return_value=['/mock/card2-DSI-1']))
        self.stack.enter_context(patch.object(pc, 'read_attr', return_value=77))
        opened = self.stack.enter_context(patch.object(pc.os, 'open', return_value=7))
        closed = self.stack.enter_context(patch.object(pc.os, 'close'))
        def fake(fd, request, buf):
            self.assertEqual(fd, 7)
            expected_sizes = {0xA7: 80, 0xA6: 20, 0xA1: 104, 0xA0: 64}
            number = request & 0xFF
            self.assertEqual(request, 0xC0006400 | (expected_sizes[number] << 16) | number)
            if number == 0xA7:
                fields = list(struct.unpack('=4Q12I', buf))
                self.assertEqual(fields[8], 77)
                self.assertEqual(fields[4], 1)  # No forced connector probe.
                fields[7], fields[9], fields[11] = 55, 16, connection
                buf[:] = struct.pack('=4Q12I', *fields)
            elif number == 0xA6:
                self.assertEqual(struct.unpack_from('=I', buf)[0], 55)
                buf[:] = struct.pack('=5I', 55, 6, crtc, 3, 0)
            elif number == 0xA1:
                self.assertEqual(struct.unpack_from('=I', buf, 12)[0], 44)
                struct.pack_into('=I', buf, 32, 1)
                struct.pack_into('=I', buf, 60, rate)
            elif number == 0xA0:
                pointer = struct.unpack_from('=Q', buf, 8)[0]
                struct.pack_into('=I', buf, 36, 3 if pointer and resource_changed else 2)
                if pointer and not resource_changed:
                    ids = (ctypes.c_uint32 * 2).from_address(pointer)
                    ids[:] = [33, 44]  # External output is pipe 0; DSI is pipe 1.
        self.stack.enter_context(patch.object(pc.fcntl, 'ioctl', side_effect=fake))
        return opened, closed

    def test_dsi_route_does_not_choose_external_pipe_zero(self):
        opened, closed = self.display_setup()
        fd, pipe, connector, original, target = pc.display()
        self.assertEqual((fd, pipe, connector, original[0], target), (7, 1, 77, 44, 120))
        opened.assert_called_once_with('/dev/dri/card2', pc.os.O_RDWR | pc.os.O_CLOEXEC)
        closed.assert_not_called()

    def test_display_rejection_closes_fd(self):
        for options in [dict(rate=90), dict(connection=2), dict(crtc=0), dict(resource_changed=True)]:
            with self.subTest(options=options), ExitStack() as temporary:
                previous = self.stack
                self.stack = temporary
                try:
                    _, closed = self.display_setup(**options)
                    with self.assertRaises(OSError):
                        pc.display()
                    closed.assert_called_once_with(7)
                finally:
                    self.stack = previous

    def calibration_setup(self, *, identity=RP6, rate=60, start=2000, ideal=2001, fail=None):
        dev = self.tmp / 'panel'
        dev.mkdir()
        attr = dev / f'frame_len_{rate}'
        attr.write_text(str(start))
        original = (44, b'mode')
        self.stack.enter_context(patch.object(pc, 'board', return_value=identity))
        self.stack.enter_context(patch.object(pc, 'panel', return_value=str(dev)))
        self.stack.enter_context(patch.object(pc, 'display', return_value=(7, 1, 77, original, rate)))
        route = self.stack.enter_context(patch.object(pc, 'route', return_value=original))
        self.stack.enter_context(patch.object(pc.time, 'sleep'))
        closed = self.stack.enter_context(patch.object(pc.os, 'close'))
        def hz(fd, pipe, seconds):
            value = int(attr.read_text())
            if fail and value != start:
                raise fail
            return rate + .01 + (ideal - value) * .1
        measure = self.stack.enter_context(patch.object(pc, 'measure', side_effect=hz))
        return attr, route, measure, closed

    def test_search_reaches_value_that_step_four_skips(self):
        attr, _, _, closed = self.calibration_setup()
        pc.calibrate()
        self.assertEqual(int(attr.read_text()), 2001)
        self.assertEqual(pc.load(RP6), {'frame_len_60': 2001})
        closed.assert_called_once_with(7)

    def test_odin_120_search_can_lower_frame_length(self):
        attr, _, _, _ = self.calibration_setup(identity=ODIN, rate=120, start=76, ideal=73)
        pc.calibrate()
        self.assertIn(int(attr.read_text()), (72, 73))
        self.assertEqual(pc.load(ODIN)['frame_len_120'], int(attr.read_text()))

    def test_nonconvergence_restores_without_saving(self):
        attr, _, measure, closed = self.calibration_setup()
        measure.side_effect = None
        measure.return_value = 60.4
        with self.assertRaises(OSError):
            pc.calibrate()
        self.assertEqual(attr.read_text(), '2000')
        self.assertFalse(Path(pc.SAVED).exists())
        closed.assert_called_once_with(7)

    def test_interruption_restores_without_saving(self):
        attr, _, _, closed = self.calibration_setup(fail=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            pc.calibrate()
        self.assertEqual(attr.read_text(), '2000')
        self.assertFalse(Path(pc.SAVED).exists())
        closed.assert_called_once_with(7)

    def test_mode_change_restores(self):
        attr, route, _, _ = self.calibration_setup()
        route.side_effect = [(44, b'mode'), (44, b'mode'), (44, b'new mode')]
        with self.assertRaisesRegex(OSError, 'mode changed'):
            pc.calibrate()
        self.assertEqual(attr.read_text(), '2000')

    def test_save_failure_restores_and_preserves_previous_file(self):
        attr, _, _, _ = self.calibration_setup()
        pc.save(RP6, {'frame_len_120': 29})
        before = Path(pc.SAVED).read_bytes()
        with patch.object(pc.os, 'replace', side_effect=OSError('read-only filesystem')):
            with self.assertRaises(OSError):
                pc.calibrate()
        self.assertEqual(attr.read_text(), '2000')
        self.assertEqual(Path(pc.SAVED).read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ['panel', 'saved.json'])

    def test_failed_write_and_failed_restore_report_uncertainty(self):
        self.calibration_setup()
        with patch.object(pc, 'write_attr', side_effect=OSError('DSI failed')) as write:
            with self.assertRaises(OSError):
                pc.calibrate()
        self.assertEqual(write.call_args_list[-1].args[1], 2000)
        self.assertIn('restore FAILED', self.errors.getvalue())
        self.assertFalse(Path(pc.SAVED).exists())

    def test_final_measurement_failure_restores(self):
        attr, _, measure, _ = self.calibration_setup()
        normal = measure.side_effect
        measure.side_effect = lambda fd, pipe, seconds: 59.9 if seconds == 3 else normal(fd, pipe, seconds)
        with self.assertRaisesRegex(OSError, 'unstable'):
            pc.calibrate()
        self.assertEqual(attr.read_text(), '2000')
        self.assertFalse(Path(pc.SAVED).exists())

    def test_apply_waits_for_probe_and_reports_transfer_failure(self):
        pc.save(RP6, {'frame_len_60': 2001, 'frame_len_120': 29})
        with patch.object(pc, 'board', return_value=RP6), \
             patch.object(pc, 'panel', side_effect=[None, '/mock/panel']), \
             patch.object(pc.time, 'sleep') as sleep, \
             patch.object(pc, 'write_attr', side_effect=[OSError('DSI failed'), None]) as write:
            with self.assertRaisesRegex(OSError, 'DSI failed'):
                pc.apply()
            self.assertEqual(write.call_count, 2)
            sleep.assert_called_once_with(.2)

    def test_apply_probe_timeout(self):
        pc.save(RP6, {'frame_len_60': 2001})
        with patch.object(pc, 'board', return_value=RP6), patch.object(pc, 'panel', return_value=None), \
             patch.object(pc.time, 'monotonic', side_effect=[0, 11]), patch.object(pc, 'write_attr') as write:
            with self.assertRaisesRegex(OSError, 'did not appear'):
                pc.apply()
            write.assert_not_called()

    def test_apply_unsupported_board_is_noop(self):
        with patch.object(pc, 'board', return_value=None), patch.object(pc, 'load') as load, \
             patch.object(pc, 'write_attr') as write:
            pc.apply()
            load.assert_not_called()
            write.assert_not_called()

    def test_writer_excludes_second_instance(self):
        with patch.object(pc.os, 'geteuid', return_value=0):
            with pc.writer():
                with self.assertRaisesRegex(OSError, 'another calibration'):
                    with pc.writer():
                        self.fail('second writer acquired lock')
            with pc.writer():
                pass


if __name__ == '__main__':
    unittest.main()
