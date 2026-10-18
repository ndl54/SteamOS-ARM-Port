#!/usr/bin/env python3
"""Fake evdev/clock/audio regressions; never opens input or runs pactl."""
import os
import io
from pathlib import Path
import runpy
import struct
import types
import unittest

HELPER = Path(os.environ.get('VOLUME_HELPER', Path(__file__).resolve().parents[2] /
    'steamos-overlay/usr/lib/steamos/sm8550-volume-keys'))


def load_helper():
    g = runpy.run_path(str(HELPER))['main'].__globals__
    def forbidden(*args, **kwargs):
        raise AssertionError("Real subprocess forbidden in volume tests")
    g['subprocess'] = types.SimpleNamespace(run=forbidden,
        DEVNULL=-3, TimeoutExpired=RuntimeError)
    return g


class StopLoop(Exception):
    pass


class Rig:
    def __init__(self, events, until=1.0, slow=0):
        self.g = load_helper()
        self.now, self.epoch = 0.0, 0.0
        self.events = list(events)
        self.until, self.slow = until, slow
        self.actions, self.closed = [], []
        self.active, self.buffers = set(), {}
        self.scan = 0
        self.wheel_fds = set()
        self.g.update(time=types.SimpleNamespace(monotonic=lambda: self.now,
            sleep=self.sleep, CLOCK_BOOTTIME=7,
            clock_gettime=lambda _: self.now + self.epoch),
            select=types.SimpleNamespace(select=self.select),
            os=types.SimpleNamespace(read=self.read, close=self.closed.append,
                path=types.SimpleNamespace(exists=lambda _: True)),
            open_devices=self.open_devices, apply=self.apply, log=lambda _: None,
            fcntl=types.SimpleNamespace(ioctl=self.ioctl))

    def open_devices(self, skip=frozenset()):
        self.scan += 1
        return [(p, fd, fd in self.wheel_fds)
                for p, fd in (('event1', 10), ('event2', 20)) if p not in skip]

    def sleep(self, seconds):
        self.now += seconds
        if self.now >= self.until:
            raise StopLoop

    def apply(self, code):
        self.actions.append((round(self.now, 3), code))
        self.now += self.slow

    def ioctl(self, fd, request, bits, mutate):
        assert request == (2 << 30) | (len(bits) << 16) | (ord('E') << 8) | 0x18
        for device, code in self.active:
            if device == fd:
                bits[code // 8] |= 1 << (code % 8)

    def read(self, fd, size):
        data = self.buffers.pop(fd)
        if isinstance(data, Exception):
            raise data
        return data

    def select(self, fds, _write, _error, timeout):
        deadline = self.now + timeout
        if self.events and self.events[0][0] <= deadline:
            when, fd, payload = self.events.pop(0)
            self.now = max(self.now, when)
            if payload == 'resume':
                self.epoch += 20
                return [], [], []
            if payload == 'silent-release':
                self.active.clear()
                return [], [], []
            if isinstance(payload, list):
                for etype, code, value in payload:
                    if etype == 1 and value in (0, 1):
                        if value:
                            self.active.add((fd, code))
                        else:
                            self.active.discard((fd, code))
                payload = b''.join(struct.pack(self.g['EVENT_FMT'], 0, 0, *e) for e in payload)
            self.buffers[fd] = payload
            assert fd in fds
            return [fd], [], []
        self.now = deadline
        if self.now >= self.until:
            raise StopLoop
        return [], [], []

    def run(self):
        with unittest.TestCase().assertRaises(StopLoop):
            self.g['main']()
        return self.actions


def key(code, value):
    return [(1, code, value)]


class VolumeHold(unittest.TestCase):
    def test_hold_and_release(self):
        r = Rig([(0, 10, key(115, 1)), (.65, 10, key(115, 0))])
        self.assertEqual(r.run(), [(0, 115), (.4, 115), (.5, 115), (.6, 115)])

    def test_release_at_deadline_precedes_repeat(self):
        r = Rig([(0, 10, key(115, 1)), (.4, 10, key(115, 0))])
        self.assertEqual(r.run(), [(0, 115)])

    def test_lost_release_checks_kernel_state(self):
        r = Rig([(0, 10, key(115, 1)), (.2, 10, 'silent-release')])
        self.assertEqual(r.run(), [(0, 115)])

    def test_eof_or_disconnect_cancels(self):
        for loss in (b'', OSError('unplug')):
            with self.subTest(loss=loss):
                r = Rig([(0, 10, key(115, 1)), (.2, 10, loss)])
                self.assertEqual(r.run(), [(0, 115)])
                self.assertIn(10, r.closed)

    def test_duplicate_press_and_hardware_repeat(self):
        r = Rig([(0, 10, key(115, 1)), (.1, 10, key(115, 1)),
                 (.2, 10, key(115, 2)), (.45, 10, key(115, 0))])
        self.assertEqual(r.run(), [(0, 115), (.4, 115)])

    def test_latest_direction_and_foreign_release(self):
        r = Rig([(0, 10, key(115, 1)), (.1, 20, key(114, 1)),
                 (.2, 10, key(115, 0)), (.55, 20, key(114, 0))])
        self.assertEqual(r.run(), [(0, 115), (.1, 114), (.5, 114)])

    def test_mute_does_not_repeat(self):
        r = Rig([(0, 10, key(113, 1)), (.1, 10, key(113, 1)),
                 (.2, 10, key(113, 2)), (.3, 10, key(113, 0))])
        self.assertEqual(r.run(), [(0, 113)])

    def test_syn_dropped_ignores_until_report(self):
        r = Rig([(0, 10, key(115, 1)), (.2, 10,
            [(0, 3, 0), (1, 114, 1), (0, 0, 0)]), (.3, 10, key(115, 0))])
        self.assertEqual(r.run(), [(0, 115)])

    def test_resume_requires_fresh_press_and_reopens(self):
        r = Rig([(0, 10, key(115, 1)), (.2, 10, 'resume'),
                 (.3, 20, key(114, 1)), (.4, 20, key(114, 0))])
        self.assertEqual(r.run(), [(0, 115), (.3, 114)])
        self.assertGreaterEqual(r.scan, 2)
        self.assertEqual(r.closed.count(10), 2)

    def test_resume_cancels_hold_without_release(self):
        r = Rig([(0, 10, key(115, 1)), (.2, 10, 'resume')])
        self.assertEqual(r.run(), [(0, 115)])

    def test_slow_command_never_catches_up(self):
        r = Rig([(0, 10, key(115, 1))], until=1.1, slow=.2)
        self.assertEqual(r.run(), [(0, 115), (.6, 115), (.9, 115)])

    def test_release_queued_during_slow_command(self):
        r = Rig([(0, 10, key(115, 1)), (.61, 10, key(115, 0))], slow=.2)
        self.assertEqual(r.run(), [(0, 115), (.6, 115)])

    def test_hotplug_reopens_without_old_hold(self):
        r = Rig([(0, 10, key(115, 1)), (.2, 10, b''),
                 (10.3, 10, key(114, 1)), (10.4, 10, key(114, 0))], until=11)
        self.assertEqual(r.run(), [(0, 115), (10.3, 114)])
        self.assertGreaterEqual(r.scan, 2)

    def test_transient_nonblocking_read_does_not_drop(self):
        r = Rig([(0, 10, key(115, 1)), (.2, 10, BlockingIOError()),
                 (.3, 10, key(115, 0))])
        self.assertEqual(r.run(), [(0, 115)])
        self.assertEqual(r.closed.count(10), 1)

    def test_cleanup_on_exit(self):
        r = Rig([])
        r.run()
        self.assertEqual(sorted(r.closed), [10, 20])

    def test_invalid_timing_uses_safe_default(self):
        g = load_helper()
        old = os.environ.get('VOLUME_TEST_TIMING')
        try:
            for value in ('0', '-1', 'nan', 'inf', 'bad', '0.001'):
                os.environ['VOLUME_TEST_TIMING'] = value
                self.assertEqual(g['hold_seconds']('VOLUME_TEST_TIMING', .4), .4)
        finally:
            if old is None:
                os.environ.pop('VOLUME_TEST_TIMING', None)
            else:
                os.environ['VOLUME_TEST_TIMING'] = old

    def test_key_state_ioctl_failure_is_closed(self):
        r = Rig([])
        r.g['fcntl'].ioctl = lambda *args: (_ for _ in ()).throw(OSError('gone'))
        self.assertFalse(r.g['key_is_down'](10, 115))

    def test_sink_limits_and_failed_query(self):
        for code, pct, expected in ((115, '98', '100%'), (114, '2', '-5%'),
                                    (115, '20', '25%')):
            with self.subTest(code=code, pct=pct):
                g = load_helper()
                calls = []
                def pactl(*args):
                    calls.append(args)
                    return {'get-default-sink': 'speaker.one\n',
                            'get-sink-volume': f'Volume: 123 / {pct}% / -1 dB'}.get(args[0], '')
                g['pactl'] = pactl
                g['apply'](code)
                self.assertIn(('set-sink-volume', 'speaker.one', expected), calls)
                self.assertFalse(any('@DEFAULT_SINK@' in c for c in calls))
        for response in ('', 'failed / nonsense', 'failed / nan%'):
            g = load_helper()
            calls = []
            def pactl(*args):
                calls.append(args)
                return 'speaker' if args[0] == 'get-default-sink' else response
            g['pactl'] = pactl
            g['apply'](115)
            self.assertFalse(any(c[0].startswith('set-') for c in calls))


class DmgWheel(unittest.TestCase):
    def test_wheel_is_one_shot_and_filters_other_events(self):
        r = Rig([(0, 10, [(2, 8, 1), (2, 8, 0), (2, 8, -1),
                         (2, 6, 1), (2, 11, 120), (1, 115, 1)]),
                 (.2, 20, [(2, 8, 1)])])
        r.wheel_fds = {10}
        self.assertEqual(r.run(), [(0, 115), (0, 114)])

    def test_wheel_obeys_syn_dropped_barrier(self):
        r = Rig([(0, 10, [(0, 3, 0), (2, 8, 1), (0, 0, 0), (2, 8, -1)])])
        r.wheel_fds = {10}
        self.assertEqual(r.run(), [(0, 114)])

    def test_wheel_obeys_suspend_barrier(self):
        r = Rig([(0, 10, [(2, 8, 1)]), (.2, 10, [(2, 8, 1)])])
        r.wheel_fds = {10}
        select = r.select
        def resume_with_queued_wheel(*args):
            result = select(*args)
            if r.now >= .2:
                r.epoch = 20
            return result
        r.g['select'].select = resume_with_queued_wheel
        self.assertEqual(r.run(), [(0, 115)])
        self.assertGreaterEqual(r.scan, 2)

    def test_wheel_keeps_independent_key_hold_and_release(self):
        r = Rig([(0, 20, key(115, 1)), (.1, 10, [(2, 8, -1)]),
                 (.45, 20, key(115, 0))])
        r.wheel_fds = {10}
        self.assertEqual(r.run(), [(0, 115), (.1, 114), (.4, 115)])

    def test_wheel_disconnect_hotplug_and_eagain(self):
        r = Rig([(0, 10, [(2, 8, 1)]), (.1, 10, BlockingIOError()),
                 (.2, 10, b''), (10.3, 10, [(2, 8, -1)])], until=11)
        r.wheel_fds = {10}
        self.assertEqual(r.run(), [(0, 115), (10.3, 114)])
        self.assertEqual(r.closed.count(10), 2)

    def test_board_requires_exact_compatible_token(self):
        g = load_helper()
        for raw, expected in ((b'ayaneo,pocketdmg\0qcom,sm8550\0', True),
                              (b'ayaneo,pocketevo\0qcom,sm8550\0', False),
                              (b'ayaneo,pocketace\0', False),
                              (b'ayaneo,pocketdmg-other\0', False), (b'', False)):
            with self.subTest(raw=raw):
                g['open'] = lambda *a, **kw: io.BytesIO(raw)
                self.assertEqual(g['is_pocket_dmg'](), expected)
        g['open'] = lambda *a, **kw: (_ for _ in ()).throw(OSError('missing'))
        self.assertFalse(g['is_pocket_dmg']())

    def test_wheel_identity_requires_vendor_product_and_input0(self):
        g = load_helper()
        for vendor, product, phys, name, expected in (
            ('1c4f', '0002', 'usb-1/input0', 'ayaneo device', True),
            ('1c4f', '0002', 'usb-1/input1', 'ayaneo device', False),
            ('1c4f', '0002', 'usb-1/input00', 'ayaneo device', False),
            ('045e', '0002', 'usb-1/input0', 'ayaneo device', False),
            ('1c4f', '0428', 'usb-1/input0', 'ayaneo device', False),
            ('1c4f', '0002', 'usb-1/input0', 'generic mouse', False)):
            with self.subTest(vendor=vendor, product=product, phys=phys, name=name):
                attrs = {'id/vendor': vendor, 'id/product': product, 'phys': phys}
                def fake_open(path, **kwargs):
                    return io.StringIO(attrs[path.split('/device/')[1]] + '\n')
                g['open'] = fake_open
                self.assertEqual(g['is_dmg_wheel']('/dev/input/event7', name), expected)
        g['open'] = lambda *a, **kw: (_ for _ in ()).throw(OSError('removed'))
        self.assertFalse(g['is_dmg_wheel']('/dev/input/event7', 'ayaneo device'))

    def test_discovery_does_not_open_wheel_on_evo_or_unrelated_device(self):
        for dmg in (False, True):
            g = load_helper()
            names = {'wheel': 'AYANEO DEVICE', 'wrong-id': 'AYANEO DEVICE',
                     'keys': 'gpio-keys', 'mouse': 'Generic mouse'}
            opened = []
            g.update(is_pocket_dmg=lambda: dmg,
                     device_name=lambda path: names[path],
                     is_dmg_wheel=lambda path, name: path == 'wheel',
                     has_volume_keys=lambda fd: fd == 10,
                     has_wheel=lambda fd: fd == 20,
                     log=lambda _: None,
                     glob=types.SimpleNamespace(glob=lambda _: list(names)),
                     os=types.SimpleNamespace(O_RDONLY=0, O_NONBLOCK=1,
                         open=lambda path, flags: opened.append(path) or
                             {'keys': 10, 'wheel': 20}[path],
                         close=lambda _: self.fail('unexpected close')))
            self.assertEqual(g['open_devices'](), [('keys', 10, False)] +
                             ([('wheel', 20, True)] if dmg else []))
            self.assertEqual(opened, ['keys'] + (['wheel'] if dmg else []))
            self.assertEqual(g['open_devices'](frozenset(names)), [])

    def test_wheel_capability_ioctl_and_missing_capability_close(self):
        g = load_helper()
        def ioctl(fd, request, bits, mutate):
            self.assertEqual(request, (2 << 30) | (2 << 16) | (ord('E') << 8) | 0x22)
            bits[1] = 1  # REL_WHEEL bit 8
        g['fcntl'] = types.SimpleNamespace(ioctl=ioctl)
        self.assertTrue(g['has_wheel'](20))
        g['fcntl'].ioctl = lambda *a: None
        self.assertFalse(g['has_wheel'](20))
        g['fcntl'].ioctl = lambda *a: (_ for _ in ()).throw(OSError('gone'))
        self.assertFalse(g['has_wheel'](20))
        closed = []
        g.update(is_pocket_dmg=lambda: True,
                 is_dmg_wheel=lambda *a: True,
                 device_name=lambda _: 'AYANEO DEVICE',
                 glob=types.SimpleNamespace(glob=lambda _: ['wheel']),
                 os=types.SimpleNamespace(O_RDONLY=0, O_NONBLOCK=1,
                     open=lambda *a: 20, close=closed.append))
        self.assertEqual(g['open_devices'](), [])
        self.assertEqual(closed, [20])


if __name__ == '__main__':
    unittest.main()
