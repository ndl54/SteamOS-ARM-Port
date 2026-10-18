#!/usr/bin/env python3
"""058 storage checks using ordinary files and command mocks, never devices."""
import importlib.machinery
import ast
import asyncio
import fcntl
import shlex
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import types
import unittest

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / 'steamos-overlay/usr/lib/steamos-arm/tablet-storage'


class Storage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tablet058-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        loader = importlib.machinery.SourceFileLoader('tablet_storage_test', str(HELPER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.m = importlib.util.module_from_spec(spec)
        loader.exec_module(self.m)
        self.m.Path = self.path
        self.m.SYS = self.path('/sys/class/block')
        self.m.SYS.mkdir(parents=True)
        self.m.STATE = self.base / 'state'
        self.m.os = types.SimpleNamespace(stat=self.devstat, sync=lambda: None,
                                          replace=os.replace, geteuid=lambda: 0, major=lambda d: d[0], minor=lambda d: d[1])
        self.m.open = lambda name, *a, **kw: open(self.path(name), *a, **kw)
        self.ids = {}
        self.calls = []
        self.fail = None
        self.bad_readback = False
        self.stale_kernel = False
        self.firmware = 'inactive'
        self.write('/sys/firmware/devicetree/base/compatible', b'lenovo,elden\0qcom,sm8750\0')
        self.write('/proc/self/mountinfo', '1 0 179:1 / / rw - ext4 /dev/mmcblk0p1 rw\n')
        self.write('/proc/swaps', 'Filename Type Size Used Priority\n')
        self.add_disk('mmcblk0', '179:0', sd=True)
        self.add_part('mmcblk0p1', 'mmcblk0', '179:1', 1, 'root', 2048, 10000)
        self.add_disk('sda', '8:0')
        self.add_part('sda1', 'sda', '8:1', 1, 'boot_a', 2048, 1000)
        self.add_part('sda2', 'sda', '8:2', 2, 'boot_b', 4096, 1000)
        self.tables = {
            'sda': self.make_table('sda', [self.entry('sda1', 'boot_a', 2048, 1000, 'RequiredPartition GUID:48,54,55'),
                                            self.entry('sda2', 'boot_b', 4096, 1000, 'GUID:49,50,51,54,60')]),
            'mmcblk0': self.make_table('mmcblk0', [self.entry('mmcblk0p1', 'root', 2048, 10000)])}
        self.mount = {'filesystems': [{'maj:min': '179:1', 'fstype': 'ext4', 'fsroot': '/', 'options': 'rw,noatime'}]}
        self.m.run = self.run_command

    def path(self, *args):
        p = Path(*args)
        if str(p).startswith(('/sys/', '/dev/', '/proc/', '/run/')):
            return self.base / str(p).lstrip('/')
        return p

    def write(self, name, value):
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            p.write_bytes(value)
        else:
            p.write_text(value)
        return p

    def add_disk(self, name, identity, sd=False):
        base = self.path('/sys/devices/platform/' + ('mmc' if sd else 'ufs') + '/block/' + name)
        base.mkdir(parents=True)
        (self.m.SYS / name).symlink_to(base)
        self.write(str(base / 'dev'), identity)
        self.write(str(base / 'ro'), '0')
        self.write(str(base / 'size'), '50000')
        (base / 'holders').mkdir()
        self.write('/dev/' + name, b'')
        self.ids[name] = identity
        link = self.path('/sys/dev/block/' + identity)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(base)
        if sd:
            self.write(str(base / 'device/type'), 'SD\n')
            self.write(str(base / 'device/cid'), '0123456789abcdef0123456789abcdef\n')
        else:
            driver = base.parents[1] / 'driver'
            driver.symlink_to(self.path('/sys/bus/platform/drivers/ufshcd-qcom'))

    def add_part(self, name, disk, identity, num, label, start, size):
        base = (self.m.SYS / disk).resolve() / name
        base.mkdir()
        (self.m.SYS / name).symlink_to(base)
        for field, value in {'partition': num, 'dev': identity, 'ro': 0, 'start': start, 'size': size,
                             'uevent': 'PARTNAME=' + label + '\n'}.items():
            self.write(str(base / field), str(value))
        (base / 'holders').mkdir()
        self.write('/dev/' + name, b'ANDROID!fixture')
        self.ids[name] = identity
        self.path('/sys/dev/block/' + identity).symlink_to(base)

    def devstat(self, name):
        major, minor = map(int, self.ids[Path(name).name].split(':'))
        return types.SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=(major, minor))

    def entry(self, name, label, start, size, attrs=None):
        p = {'node': '/dev/' + name, 'start': start, 'size': size, 'type': '0FC63DAF-8483-4772-8E79-3D69D8477DE4',
             'uuid': 'uuid-' + name, 'name': label}
        if attrs:
            p['attrs'] = attrs
        return p

    def make_table(self, name, parts):
        return {'device': '/dev/' + name, 'id': 'disk-' + name, 'label': 'gpt', 'unit': 'sectors',
                'sectorsize': 512, 'firstlba': 34, 'lastlba': 30000, 'partitions': parts}

    def run_command(self, *args, input=None, timeout=30):
        self.calls.append((args, input))
        if self.fail and self.fail in args:
            raise subprocess.CalledProcessError(1, args)
        if args[0] == 'findmnt':
            return json.dumps(self.mount)
        if args[0] == 'systemctl':
            return self.firmware if 'show' in args else ''
        if args[0] == 'sfdisk':
            disk = Path(args[-1]).name
            t = self.tables[disk]
            if '--json' in args:
                return json.dumps({'partitiontable': t})
            if '--verify' in args:
                return ''
            if '--dump' in args:
                lines = ['label: gpt', 'label-id: ' + t['id'], 'unit: sectors']
                for p in t['partitions']:
                    lines.append(p['node'] + ' : start=' + str(p['start']) + ', size=' + str(p['size'])
                                 + (', attrs="' + p['attrs'] + '"' if p.get('attrs') else ''))
                return '\n'.join(lines)
            if '--backup-pt-sectors' in args:
                dest = Path(args[args.index('--backup-file') + 1] + '-' + disk + '-0x0.bak')
                dest.write_text('fake binary sectors')
                return ''
            self.assertIsNotNone(input)
            self.assertIn('--wipe=never', args)
            self.assertNotIn('--force', args)
            if '-N' in args:
                self.assertEqual(input, '2048, +\n')
                t['partitions'][0]['size'] = 20000
            else:
                for p in t['partitions']:
                    line = next(x for x in input.splitlines() if x.startswith(p['node'] + ' :'))
                    match = re.search(r'attrs="([^"]*)"', line)
                    if match:
                        p['attrs'] = match[1]
                    else:
                        p.pop('attrs', None)
            if self.bad_readback:
                t['partitions'][0]['start'] += 1
            return ''
        if args[0] == 'partx':
            if not self.stale_kernel:
                self.write(str(self.m.SYS / 'mmcblk0p1/size'), '20000')
            return ''
        if args[0] == 'blockdev':
            return str(int((self.m.SYS / 'mmcblk0p1/size').read_text()) * 512)
        if args[0] == 'blkid':
            return '01234567-89ab-cdef-0123-456789abcdef'
        if args[0] == 'resize2fs':
            return ''
        self.fail_test('unexpected command: ' + repr(args))

    def fail_test(self, msg):
        raise AssertionError(msg)

    def writes(self):
        return [x for x in self.calls if x[1] is not None]

    def test_slot_transaction_preserves_unrelated_bits_and_reboots_after_readback(self):
        self.m.switch_android()
        self.assertEqual(len(self.writes()), 1)
        a, b = self.tables['sda']['partitions']
        self.assertEqual(self.m.bits(a['attrs']), {0, 48, 50, 51, 52, 53, 54})
        self.assertEqual(self.m.bits(b['attrs']), {49, 51, 54, 60})
        self.assertEqual(self.calls[-1][0], ('systemctl', '--no-block', 'reboot'))
        self.assertTrue(list(self.m.STATE.glob('slot-*/table.sfdisk')))

    def test_slot_rejects_conflicting_or_missing_active_state(self):
        for a, b in (('GUID:50', 'GUID:50'), ('', ''), ('GUID:50', '')):
            self.tables['sda']['partitions'][0]['attrs'] = a
            self.tables['sda']['partitions'][1]['attrs'] = b
            with self.assertRaises(RuntimeError):
                self.m.switch_android()
        self.assertFalse(self.writes())

    def test_slot_failure_never_reboots(self):
        for fail in ('--backup-pt-sectors', '--lock=yes'):
            self.calls.clear()
            self.fail = fail
            with self.assertRaises(subprocess.CalledProcessError):
                self.m.switch_android()
            self.assertFalse(any('reboot' in x[0] for x in self.calls))
        self.fail = None
        self.bad_readback = True
        with self.assertRaises(RuntimeError):
            self.m.switch_android()
        self.assertFalse(any('reboot' in x[0] for x in self.calls))

    def test_rejected_reboot_keeps_selected_slot_and_backup(self):
        self.fail = 'reboot'
        with self.assertRaises(subprocess.CalledProcessError):
            self.m.switch_android()
        self.assertIn(50, self.m.bits(self.tables['sda']['partitions'][0]['attrs']))
        self.assertTrue(list(self.m.STATE.glob('slot-*/table.json')))

    def test_firmware_active_or_storage_changed_before_write(self):
        self.firmware = 'active'
        with self.assertRaises(RuntimeError):
            self.m.switch_android()
        self.assertFalse(self.writes())
        self.firmware = 'inactive'
        original = self.m.backup
        def changed(*args):
            original(*args)
            self.tables['sda']['id'] = 'changed'
        self.m.backup = changed
        with self.assertRaises(RuntimeError):
            self.m.switch_android()
        self.assertFalse(self.writes())

    def test_exact_board_and_sd_type(self):
        for compat in (b'lenovo,tb321fu\0', b'ayaneo,pocketevo\0', b'lenovo,elden-extra\0'):
            self.write('/sys/firmware/devicetree/base/compatible', compat)
            with self.assertRaises(RuntimeError):
                self.m.sd_root()
        self.write('/sys/firmware/devicetree/base/compatible', b'qcom,sm8750\0lenovo,elden\0')
        self.m.sd_root()
        self.write(str(self.m.SYS / 'mmcblk0/device/type'), 'MMC')
        with self.assertRaises(RuntimeError):
            self.m.sd_root()
        self.assertFalse(self.writes())

    def test_direct_ext4_root_required(self):
        for key, value in (('fstype', 'overlay'), ('fsroot', '/subdir'), ('options', 'ro')):
            old = self.mount['filesystems'][0][key]
            self.mount['filesystems'][0][key] = value
            with self.assertRaises(RuntimeError):
                self.m.sd_root()
            self.mount['filesystems'][0][key] = old

    def test_duplicate_slot_labels_rejected(self):
        self.add_part('sda3', 'sda', '8:3', 3, 'boot_a', 6000, 1000)
        with self.assertRaises(RuntimeError):
            self.m.slots()
        self.assertFalse(self.writes())

    def test_usb_ancestry_mounts_and_holders_rejected(self):
        driver = self.path('/sys/devices/platform/ufs/driver')
        driver.unlink()
        driver.symlink_to(self.path('/sys/bus/usb/drivers/usb-storage'))
        with self.assertRaises(RuntimeError):
            self.m.slots()
        driver.unlink()
        driver.symlink_to(self.path('/sys/bus/platform/drivers/ufshcd-qcom'))
        self.write('/proc/self/mountinfo', '1 0 8:1 / /boot rw - ext4 /dev/disk/by-uuid/alias rw\n')
        with self.assertRaises(RuntimeError):
            self.m.slots()
        self.write('/proc/self/mountinfo', '')
        (self.m.SYS / 'sda2/holders/dm-0').touch()
        with self.assertRaises(RuntimeError):
            self.m.slots()

    def test_loop_backing_exclusion_without_holder(self):
        self.write(str(self.m.SYS / 'loop0/loop/backing_file'), '/dev/sda2\n')
        with self.assertRaises(RuntimeError):
            self.m.slots()
        self.assertFalse(self.writes())

    def test_boot_magic_uuid_and_geometry_rejected(self):
        self.write('/dev/sda1', b'not Android')
        with self.assertRaises(RuntimeError):
            self.m.slots()
        self.write('/dev/sda1', b'ANDROID!')
        self.tables['sda']['partitions'][0]['start'] += 1
        with self.assertRaises(RuntimeError):
            self.m.slots()
        self.tables['sda']['partitions'][0]['start'] -= 1
        self.tables['sda']['partitions'][0]['uuid'] = 'uuid-sda2'
        with self.assertRaises(RuntimeError):
            self.m.slots()

    def test_growth_success_and_identity_bound_idempotence(self):
        self.m.grow()
        marker = self.m.STATE / 'sd-grown'
        self.assertIn('cid', json.loads(marker.read_text()))
        self.assertEqual(len(self.writes()), 1)
        self.calls.clear()
        self.m.grow()
        self.assertFalse(self.writes())
        # An old empty source marker cannot suppress validation/growth.
        marker.write_text('')
        self.tables['mmcblk0']['partitions'][0]['size'] = 10000
        self.write(str(self.m.SYS / 'mmcblk0p1/size'), '10000')
        self.m.grow()
        self.assertEqual(len(self.writes()), 1)

    def test_growth_failures_do_not_stamp_and_can_retry(self):
        for command in ('--backup-pt-sectors', '--lock=yes', 'partx', 'resize2fs'):
            self.tables['mmcblk0']['partitions'][0]['size'] = 10000
            self.write(str(self.m.SYS / 'mmcblk0p1/size'), '10000')
            self.fail = command
            with self.assertRaises(subprocess.CalledProcessError):
                self.m.grow()
            self.assertFalse((self.m.STATE / 'sd-grown').exists())
        self.fail = None
        self.m.grow()
        self.assertTrue((self.m.STATE / 'sd-grown').exists())

    def test_stale_kernel_geometry_stops_before_resize(self):
        self.stale_kernel = True
        with self.assertRaises(RuntimeError):
            self.m.grow()
        self.assertFalse(any(x[0][0] == 'resize2fs' for x in self.calls))
        self.assertFalse((self.m.STATE / 'sd-grown').exists())

    def test_whole_card_and_other_partitions_swap_excluded(self):
        self.mount['filesystems'][0]['maj:min'] = '179:0'
        self.m.grow()
        self.assertFalse(self.writes())
        self.mount['filesystems'][0]['maj:min'] = '179:1'
        self.write('/proc/swaps', 'header\n/swapfile file 100 0 -2\n')
        with self.assertRaises(RuntimeError):
            self.m.grow()
        self.write('/proc/swaps', 'header\n')
        self.add_part('mmcblk0p2', 'mmcblk0', '179:2', 2, 'home', 14000, 1000)
        with self.assertRaises(RuntimeError):
            self.m.grow()
        self.assertFalse(self.writes())

    def test_shared_lock_blocks_concurrent_mutation(self):
        lock = self.path('/run/lock/tablet-gpt.lock')
        lock.parent.mkdir(parents=True)
        self.m.sys = types.SimpleNamespace(argv=['tablet-storage', 'slot', 'android'])
        with lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.m.main()
        self.assertFalse(self.calls)

    def test_bit_parser_roundtrip_and_reject_unknown(self):
        for bits in (set(), {0, 1, 2, 48, 50, 54, 63}, {55}):
            self.assertEqual(self.m.bits(self.m.attrs(bits)), bits)
        for bad in ('GUID:3', 'GUID:64', 'GUID:50foo', 'unknown', 'GUID:'):
            with self.assertRaises(RuntimeError):
                self.m.bits(bad)


class BootAndUI(unittest.TestCase):
    def test_explicit_device_wait_and_exact_elden_log_isolation(self):
        text = (REPO / 'external-and-mods/kernel-common/initramfs/init').read_text()
        fragment = text[text.index('bootdev=""\nrootdev=""'):text.index('\nlogdir=""')]
        for board, available, expected in (('lenovo,elden', 1, '/dev/mmcblk0|'),
                ('lenovo,elden', 3, '/dev/mmcblk0|'), ('lenovo,elden', 99, '|'),
                ('lenovo,tb321fu', 1, '/dev/mmcblk0|/mock/boot'),
                ('ayaneo,pocketevo', 1, '/dev/mmcblk0|/mock/boot'),
                ('lenovo,elden-extra', 1, '/dev/mmcblk0|/mock/boot')):
            with self.subTest(board=board, available=available), tempfile.TemporaryDirectory() as tmp:
                compat = Path(tmp) / 'compatible'
                compat.write_bytes((board + '\0qcom,soc\0').encode())
                script = fragment.replace('/sys/firmware/devicetree/base/compatible', shlex.quote(str(compat)))
                script = script.replace('[ -b "$rootarg" ]', 'is_block "$rootarg"')
                prelude = f'''rootarg=/dev/mmcblk0; bootlabel=ROCKNIX; n=0
is_block() {{ n=$((n+1)); [ "$n" -ge {available} ]; }}
sleep() {{ :; }}
by_partlabel() {{ echo /mock/boot; }}
'''
                result = subprocess.run(['sh', '-c', prelude + script + '\nprintf "%s|%s" "$rootdev" "$bootdev"'],
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, expected)

    def test_plugin_checks_and_missing_helper_fail_closed(self):
        path = REPO / 'external-and-mods/Decky/sm8650/konkr-control/main.py'
        tree = ast.parse(path.read_text())
        method = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Plugin')
        method = next(n for n in method.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'boot_android')
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'dualboot'] + [method]
        calls = []
        def run(*args, **kwargs):
            calls.append(args[0])
            return types.SimpleNamespace(returncode=0)
        sub = types.SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired)
        ns = {'asyncio': asyncio, 'subprocess': sub, 'Any': object}
        exec(compile(tree, str(path), 'exec'), ns)
        self.assertTrue(asyncio.run(ns['boot_android'](object())))
        self.assertEqual([c[-1] for c in calls], ['check', 'android'])
        def missing(*a, **kw):
            raise FileNotFoundError('mock missing helper')
        sub.run = missing
        self.assertFalse(ns['dualboot']())
        self.assertFalse(asyncio.run(ns['boot_android'](object())))


if __name__ == '__main__':
    unittest.main()
