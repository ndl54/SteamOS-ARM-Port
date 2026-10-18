#!/usr/bin/env python3
"""Gen5 source/ordinary-file mocks only. No builder, mount, block or service call."""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


old = load(REPO / 'scripts/tests/test-tablet-sd-runtime.py', 'gen5_fixture')


class Storage(unittest.TestCase):
    def setUp(self):
        self.f = old.Storage()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        self.g = g = load(REPO / 'steamos-overlay/usr/lib/steamos-arm/gen5-storage', 'gen5_test')
        g.s = f.m
        g.Path = f.path
        g.open = lambda p, *a, **kw: open(f.path(p), *a, **kw)
        g.os = f.m.os
        f.m.board = g.board
        g.run = self.command
        g.HASH = f.base / 'android.sha256'
        g.FW = f.base / 'firmware/baldur'
        g.MANIFEST = f.base / 'manifest.tsv'
        f.m.STATE.mkdir()
        f.write('/sys/firmware/devicetree/base/compatible', b'lenovo,baldur\0qcom,kaanapali\0')
        f.write('/proc/self/mountinfo', '1 0 179:2 / / rw - ext4 /dev/mmcblk0p2 rw\n')
        f.write(str(f.m.SYS / 'mmcblk0p1/uevent'), 'PARTNAME=steamos-gen5-logs\n')
        f.add_part('mmcblk0p2', 'mmcblk0', '179:2', 2, 'steamos-gen5', 13000, 10000)
        f.mount['filesystems'][0]['maj:min'] = '179:2'
        logs = f.entry('mmcblk0p1', 'steamos-gen5-logs', 2048, 10000)
        logs['type'] = 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'
        f.tables['mmcblk0']['partitions'] = [logs, f.entry('mmcblk0p2', 'steamos-gen5', 13000, 10000)]
        f.tables['sda']['partitions'][0]['attrs'] = 'GUID:50'
        f.tables['sda']['partitions'][1]['attrs'] = ''
        f.write('/dev/sda1', b'ANDROID!linux')
        f.write('/dev/sda2', b'ANDROID!stock')
        g.HASH.write_text(g.digest('/dev/sda2') + '\n')
        self.calls = []
        self.fail = None
        self.bad = False

    def command(self, *args, input=None, timeout=30):
        self.calls.append(args)
        if args[0] == self.fail:
            raise subprocess.CalledProcessError(1, args)
        f = self.f
        if args[0] == 'dd':
            a = next(x[3:] for x in args if x.startswith('if='))
            b = next(x[3:] for x in args if x.startswith('of='))
            f.path(b).write_bytes(f.path(a).read_bytes() if not self.bad else b'bad')
        elif args[0] == 'blockdev':
            return str(20000 * 512)
        elif args[0] == 'sfdisk':
            if '--verify' in args:
                return ''
            self.assertEqual(args[args.index('-N') + 1], '2')
            self.assertEqual(input, '13000, +\n')
            f.tables['mmcblk0']['partitions'][1]['size'] = 20000
            if self.bad:
                f.tables['mmcblk0']['partitions'][0]['start'] += 1
        elif args[0] == 'partx':
            f.write(str(f.m.SYS / 'mmcblk0p2/size'), '20000')
        elif args[0] == 'blkid':
            return '01234567-89ab-cdef-0123-456789abcdef'
        elif args[0] not in ('resize2fs', 'systemctl', 'mount', 'umount'):
            self.fail_test('unexpected command ' + str(args))
        return ''

    def fail_test(self, msg):
        raise AssertionError(msg)

    def test_board_is_exact_and_elden_stays_separate(self):
        self.g.board()
        for board in (b'lenovo,baldur-plus\0', b'lenovo,elden\0', b'ayaneo,pocketevo\0', b'qcom,kaanapali\0'):
            self.f.write('/sys/firmware/devicetree/base/compatible', board)
            with self.assertRaises(RuntimeError): self.g.board()
        self.assertIn("b'lenovo,elden'", (REPO / 'steamos-overlay/usr/lib/steamos-arm/tablet-storage').read_text())

    def test_card_identity(self):
        self.assertEqual(self.g.card()[0].name, 'mmcblk0p2')
        for key, value in [('name', 'other'), ('type', 'other'), ('start', 1), ('uuid', 'uuid-mmcblk0p1')]:
            entry = self.f.tables['mmcblk0']['partitions'][1]
            previous = entry[key]; entry[key] = value
            with self.assertRaises(RuntimeError): self.g.card()
            entry[key] = previous
        self.f.write(str(self.f.m.SYS / 'mmcblk0/device/type'), 'MMC')
        with self.assertRaises(RuntimeError): self.g.card()

    def test_card_mount_holder_and_loop_rejection(self):
        f = self.f
        f.write('/proc/self/mountinfo', '1 0 179:1 / /logs rw - vfat /dev/mmcblk0p1 rw\n')
        with self.assertRaises(RuntimeError): self.g.card()
        f.write('/proc/self/mountinfo', '')
        h = f.m.SYS / 'mmcblk0p1/holders/dm-0'; h.touch()
        with self.assertRaises(RuntimeError): self.g.card()
        h.unlink()
        f.write('/sys/class/block/loop0/loop/backing_file', '/dev/mmcblk0p1')
        with self.assertRaises(RuntimeError): self.g.card()

    def test_android_check_no_writes_and_bad_hash(self):
        self.g.android(True)
        self.assertEqual(self.calls, [])
        self.g.HASH.write_text('f' * 64)
        with self.assertRaises(RuntimeError): self.g.android()
        self.assertEqual(self.calls, [])

    def test_android_backup_readback_reboot(self):
        self.g.android()
        backup = next(self.f.m.STATE.glob('gen5-boot-*'))
        self.assertEqual((backup / 'boot_a.img').read_bytes(), b'ANDROID!linux')
        self.assertEqual([x[0] for x in self.calls], ['dd', 'blockdev', 'systemctl'])
        self.assertEqual(self.f.path('/dev/sda1').read_bytes(), b'ANDROID!stock')

    def test_android_write_failure_keeps_backup_no_reboot(self):
        for command in ('dd', 'blockdev'):
            self.calls.clear(); self.fail = command
            with self.assertRaises(subprocess.CalledProcessError): self.g.android()
            self.assertFalse(any(x[0] == 'systemctl' for x in self.calls))
            self.assertTrue(list(self.f.m.STATE.glob('gen5-boot-*/boot_a.img')))

    def test_android_corrupt_readback_and_wrong_active_slot(self):
        self.bad = True
        with self.assertRaises(RuntimeError): self.g.android()
        self.assertFalse(any(x[0] == 'systemctl' for x in self.calls))
        self.f.write('/dev/sda1', b'ANDROID!linux')
        self.f.tables['sda']['partitions'][1]['attrs'] = 'GUID:50'
        with self.assertRaises(RuntimeError): self.g.android(True)

    def test_grow_success_idempotent_preserves_logs(self):
        before = dict(self.f.tables['mmcblk0']['partitions'][0])
        self.g.grow()
        self.assertEqual(self.f.tables['mmcblk0']['partitions'][0], before)
        self.assertTrue((self.f.m.STATE / 'gen5-sd-grown').exists())
        self.calls.clear(); self.g.grow()
        self.assertEqual([x[0] for x in self.calls], ['sfdisk', 'blkid'])

    def test_grow_failed_resize_has_no_marker(self):
        self.fail = 'resize2fs'
        with self.assertRaises(subprocess.CalledProcessError): self.g.grow()
        self.assertFalse((self.f.m.STATE / 'gen5-sd-grown').exists())
        self.fail = None; self.g.grow()
        self.assertTrue((self.f.m.STATE / 'gen5-sd-grown').exists())

    def test_grow_changed_other_partition_stops(self):
        self.bad = True
        with self.assertRaises(RuntimeError): self.g.grow()
        self.assertFalse(any(c[0] == 'resize2fs' for c in self.calls))

    def test_early_root_discovery_rejects_duplicate_and_emmc(self):
        src = (REPO / 'external-and-mods/kernel-common/initramfs/init').read_text()
        fn = src[src.index('gen5_card() {'):src.index('\nbootdev=""', src.index('gen5_card() {'))]
        fn = fn.replace('/sys/', str(self.f.base / 'sys') + '/').replace('/dev/', str(self.f.base / 'dev') + '/')
        fn = fn.replace('[ -b ', '[ -f ')
        script = fn + '\nif gen5_card; then printf "%s|%s" "$rootdev" "$bootdev"; else exit 1; fi'
        result = subprocess.run(['sh', '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('mmcblk0p2|', result.stdout)
        self.f.write(str(self.f.m.SYS / 'mmcblk0/device/type'), 'MMC')
        self.assertNotEqual(subprocess.run(['sh', '-c', script], capture_output=True).returncode, 0)
        self.f.write(str(self.f.m.SYS / 'mmcblk0/device/type'), 'SD')
        self.f.add_part('sda3', 'sda', '8:3', 3, 'steamos-gen5', 9000, 1000)
        self.assertNotEqual(subprocess.run(['sh', '-c', script], capture_output=True).returncode, 0)

    def archive(self, members):
        archive = self.f.base / 'firmware.tar'
        with tarfile.open(archive, 'w') as t:
            for name, data, kind in members:
                info = tarfile.TarInfo(name); info.size = len(data); info.type = kind
                t.addfile(info, io.BytesIO(data))
        return archive

    def test_firmware_complete_hashes_and_no_traversal_links_duplicates(self):
        data = b'signed-fixture'
        self.g.MANIFEST.write_text('qcom/test.bin\t' + hashlib.sha256(data).hexdigest() + '\t/vendor/test\tcopy\n')
        dest = self.f.base / 'out'; dest.mkdir()
        valid = ('./qcom/test.bin', data, tarfile.REGTYPE)
        self.g.unpack(self.archive([valid]), dest)
        self.assertEqual((dest / 'qcom/test.bin').read_bytes(), data)
        for rows in ([], [valid, valid], [('../escape', data, tarfile.REGTYPE)],
                     [('qcom/test.bin', data, tarfile.SYMTYPE)], [('qcom/test.bin', b'wrong', tarfile.REGTYPE)]):
            with self.assertRaises(RuntimeError): self.g.unpack(self.archive(rows), dest)

    def test_firstboot_publishes_only_complete_generation_and_unmounts(self):
        g = self.g
        data = b'firmware'
        g.MANIFEST.write_text('qcom/test.bin\t' + hashlib.sha256(data).hexdigest() + '\t/vendor/test\tcopy\n')
        archive = self.archive([('qcom/test.bin', data, tarfile.REGTYPE)])
        realrun = self.command
        def run(*args, **kw):
            if args[0] == 'mount':
                d = Path(args[-1]); (d / 'firmware.tar').write_bytes(archive.read_bytes())
                (d / 'android-boot.sha256').write_text('a' * 64)
            if args[0] == 'umount':
                for p in Path(args[-1]).iterdir(): p.unlink()
            return realrun(*args, **kw)
        g.run = run
        g.firstboot()
        self.assertTrue(g.FW.is_symlink())
        first = g.FW.resolve()
        self.assertEqual((first / 'qcom/test.bin').read_bytes(), data)
        self.archive([('qcom/test.bin', b'bad', tarfile.REGTYPE)])
        with self.assertRaises(RuntimeError): g.firstboot()
        self.assertEqual(g.FW.resolve(), first)
        self.assertEqual(self.calls[-1][0], 'umount')


class EmergencyKey(unittest.TestCase):
    def test_current_key_state_and_no_repeated_write_while_held(self):
        m = load(REPO / 'steamos-overlay/usr/lib/steamos-arm/gen5-emergency-key', 'gen5_keys_test')
        def ioctl(fd, request, data, mutate):
            self.assertEqual(request, 0x80604518)
            data[:] = ((1 << 114) | (1 << 115)).to_bytes(96, 'little')
        m.fcntl = types.SimpleNamespace(ioctl=ioctl)
        self.assertEqual(m.pressed(5), {114, 115})
        m.open = lambda *a, **kw: io.BytesIO(b'lenovo,baldur\0')
        m.key_devices = lambda: ['mock-event']
        closed, calls = [], []
        m.os = types.SimpleNamespace(open=lambda *a: 5, close=closed.append, O_RDONLY=0, O_NONBLOCK=0)
        clock = [0]
        def sleep(n):
            clock[0] += n
            if clock[0] > 25:
                raise InterruptedError('end mock')
        m.time = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)
        m.subprocess = types.SimpleNamespace(run=lambda *a, **kw: calls.append(a))
        with self.assertRaises(InterruptedError): m.main()
        self.assertEqual(len(calls), 1)
        self.assertEqual(closed, [5])


class BootImage(unittest.TestCase):
    def setUp(self):
        self.m = load(REPO / 'scripts/gen5/boot-repack.py', 'gen5_repack_test')
        data = bytearray(32768)
        data[:8] = b'ANDROID!'
        for offset, value in [(8, 64), (20, 1584), (40, 4)]: struct.pack_into('<I', data, offset, value)
        data[4096+56:4096+60] = b'ARM\x64'
        data[8192:8196] = b'AVB0'; data[12288:12292] = b'AVB0'
        struct.pack_into('>4sIIQQQ', data, len(data)-64, b'AVBf', 1, 0, 12288, 12288, 256)
        self.data = bytes(data)

    def test_identity_and_repack_preserve_signatures(self):
        m = self.m.StockBoot(self.data)
        self.assertEqual(m.repack(m.kernel), self.data)
        new = m.repack(m.kernel + b'X' * 4096)
        n = self.m.StockBoot(new)
        self.assertEqual(n.vbmeta, m.vbmeta)
        self.assertEqual(n.boot_signature, m.boot_signature)
        self.assertEqual(len(new), len(self.data))

    def test_truncated_and_out_of_bounds_rejected(self):
        for blob in (b'ANDROID!', self.data[:100], self.data[:-1]):
            with self.assertRaises(SystemExit): self.m.StockBoot(blob)
        bad = bytearray(self.data); struct.pack_into('>Q', bad, len(bad)-64+28, 1000000)
        with self.assertRaises(SystemExit): self.m.StockBoot(bad)
        with self.assertRaises(SystemExit): self.m.StockBoot(self.data).repack(b'X' * 50000)


if __name__ == '__main__':
    unittest.main()
