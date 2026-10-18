#!/usr/bin/env python3
"""Ordinary-file sysfs fixture; no block nodes, mount, format or real blkid."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'steamos-overlay/usr/lib/steamos-arm/is-old-system-card'
loader = importlib.machinery.SourceFileLoader('old_card', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
s = importlib.util.module_from_spec(spec)
loader.exec_module(s)


class CardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.sys = self.base / 'sys/class/block'
        self.dev = self.base / 'dev'
        self.proc = self.base / 'proc'
        for p in (self.sys, self.dev, self.proc / 'self', self.base / 'sys/dev/block'):
            p.mkdir(parents=True)
        self.stats = {}
        self.sd = self.disk('mmcblk1', 9, 'mmc')
        self.ufs = self.disk('sda', 8, 'ufs')
        self.put(self.sd / 'device/type', 'SD')
        self.put(self.sd / 'device/cid', '1' * 32)
        self.put(self.sd / 'diskseq', '42')
        driver = self.base / 'drivers/ufshcd-qcom'
        driver.mkdir(parents=True)
        (self.ufs.parent / 'driver').symlink_to(driver)
        self.rows = ['1 0 8:1 / / rw - ext4 /dev/root rw',
                     '2 1 8:2 / /boot rw - vfat /dev/disk/by-label/ROCKNIX rw',
                     '3 1 8:3 / /home rw - ext4 /dev/sda3 rw']
        self.mounts()
        self.put(self.proc / 'swaps', 'Filename Type Size Used Priority\n')
        self.labels = dict(zip(('mmcblk1p1', 'mmcblk1p2', 'mmcblk1p3'),
                               (('BOOT', 'vfat'), ('root', 'ext4'), ('home', 'ext4'))))
        original_stat = Path.stat

        def fake_stat(path, *args, **kwargs):
            # Block identity is synthetic; all other filesystem reads stay
            # inside this private ordinary-file tree.
            if str(path) in self.stats:
                return self.stats[str(path)]
            return original_stat(path, *args, **kwargs)

        for obj, key, value in ((s, 'SYS', self.sys), (s, 'DEV', self.dev),
                                (s, 'PROC', self.proc), (Path, 'stat', fake_stat)):
            p = patch.object(obj, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.run = patch.object(s.subprocess, 'run', side_effect=self.probe).start()
        self.addCleanup(patch.stopall)

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def disk(self, name, major, host):
        disk = self.base / 'sys/devices' / host / name
        for index in range(4):
            child = name if index == 0 else name + ('p' if name.startswith('mmc') else '') + str(index)
            node = disk if index == 0 else disk / child
            node.mkdir(parents=True, exist_ok=True)
            (self.sys / child).symlink_to(node)
            (self.base / 'sys/dev/block' / f'{major}:{index}').symlink_to(node)
            self.put(node / 'dev', f'{major}:{index}')
            self.put(node / 'ro', '0')
            self.put(node / 'size', '100000' if index == 0 else '10000')
            (node / 'holders').mkdir()
            if index:
                self.put(node / 'partition', str(index))
                self.put(node / 'start', str(index * 10000))
            else:
                (node / 'slaves').mkdir()
            self.stats[str(self.dev / child)] = SimpleNamespace(
                st_mode=stat.S_IFBLK, st_rdev=os.makedev(major, index))
        return disk

    def mounts(self):
        self.put(self.proc / 'self/mountinfo', '\n'.join(self.rows) + '\n')

    def probe(self, args, **kwargs):
        self.assertEqual(args[:8], ['blkid', '-p', '-o', 'export', '-s', 'LABEL', '-s', 'TYPE'])
        self.assertEqual(Path(args[8]).parent, self.dev)
        self.assertEqual(kwargs, dict(check=True, capture_output=True, text=True, timeout=2))
        label, fs = self.labels[Path(args[8]).name]
        return SimpleNamespace(stdout=f'LABEL={label}\nTYPE={fs}\n')

    def rejected(self, name='mmcblk1p2'):
        with self.assertRaises((ValueError, OSError, subprocess.SubprocessError)):
            s.old_card(name)

    def test_idle_card_all_partition_events(self):
        for part in (1, 2, 3):
            s.old_card('mmcblk1p' + str(part))
        self.assertEqual(self.run.call_count, 9)

    def test_emmc_and_unknown_identity(self):
        for kind in ('MMC', '', 'SDIO'):
            self.put(self.sd / 'device/type', kind)
            self.rejected()
        self.put(self.sd / 'device/type', 'SD')
        self.put(self.sd / 'device/cid', '')
        self.rejected()
        self.assertEqual(self.run.call_count, 0)

    def test_whole_disk_ufs_and_untrusted_names(self):
        for name in ('mmcblk1', 'sda1', '../mmcblk1p2', 'mmcblk1p20', 'mmcblk1p2 x'):
            self.rejected(name)
        self.assertEqual(self.run.call_count, 0)

    def test_running_sd_and_boot_or_home_on_sd(self):
        original = self.rows[:]
        for index in range(3):
            self.rows = original[:]
            self.rows[index] = self.rows[index].replace(f'8:{index + 1}', f'9:{index + 1}')
            self.mounts()
            self.rejected()
        self.assertEqual(self.run.call_count, 0)

    def test_missing_boot_overlay_usb_bind_or_ambiguous_root(self):
        original = self.rows[:]
        cases = [original[:1], [original[0].replace('ext4', 'overlay'), *original[1:]],
                 [original[0].replace(' / / ', ' /subdir / '), *original[1:]],
                 original + [original[0]]]
        for rows in cases:
            self.rows = rows
            self.mounts()
            self.rejected()
        self.rows = original
        self.mounts()
        (self.ufs.parent / 'driver').unlink()
        self.rejected()

    def test_mount_alias_or_bind_any_partition_or_whole_card(self):
        for minor in range(4):
            self.rows.append(f'4 1 9:{minor} /subdir /somewhere rw - ext4 /dev/alias rw')
            self.mounts()
            self.rejected()
            self.rows.pop()

    def test_swap_block_and_file(self):
        for kind in ('partition', 'file'):
            name = self.dev / 'mmcblk1p3' if kind == 'partition' else self.base / 'swap file'
            if kind == 'file':
                self.stats[str(name)] = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=os.makedev(9, 3))
            encoded = str(name).replace(' ', r'\040')
            self.put(self.proc / 'swaps', f'Filename Type Size Used Priority\n{encoded} {kind} 10 0 -1\n')
            self.rejected()

    def test_loop_backing_block_file_unresolved_and_unrelated(self):
        backing = self.sys / 'loop0/loop/backing_file'
        for name in (self.dev / 'mmcblk1p3', self.base / 'backing file', self.base / 'missing'):
            if name.name == 'backing file':
                self.stats[str(name)] = SimpleNamespace(st_mode=stat.S_IFREG, st_dev=os.makedev(9, 3))
            self.put(backing, str(name).replace(' ', r'\040'))
            self.rejected()
        self.put(backing, str(self.dev / 'sda3'))
        s.old_card('mmcblk1p2')

    def test_active_loop_without_backing_evidence(self):
        self.put(self.sys / 'loop0/size', '100')
        self.rejected()
        self.put(self.sys / 'loop0/size', '0')
        s.old_card('mmcblk1p2')

    def test_holder_and_readonly(self):
        holder = self.sd / 'mmcblk1p2/holders/dm-0'
        holder.touch()
        self.rejected()
        holder.unlink()
        self.put(self.sd / 'ro', '1')
        self.rejected()

    def test_bad_geometry_extra_partition_or_wrong_parent(self):
        self.put(self.sd / 'mmcblk1p2/start', '1')
        self.rejected()
        self.put(self.sd / 'mmcblk1p2/start', '20000')
        extra = self.sd / 'mmcblk1p4/partition'
        self.put(extra, '4')
        self.rejected()
        extra.unlink()
        link = self.sys / 'mmcblk1p2'
        link.unlink()
        link.symlink_to(self.ufs / 'sda2')
        self.rejected()

    def test_wrong_dev_number_or_nonblock(self):
        node = str(self.dev / 'mmcblk1p2')
        self.stats[node] = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(9, 1))
        self.rejected()
        self.stats[node] = SimpleNamespace(st_mode=stat.S_IFREG, st_rdev=os.makedev(9, 2))
        self.rejected()

    def test_wrong_labels_types_or_missing_partition_probe(self):
        for pair in (('ROOT', 'ext4'), ('root', 'btrfs'), ('BOOT root home', 'ext4')):
            self.labels['mmcblk1p2'] = pair
            self.rejected()
        for error in (subprocess.CalledProcessError(2, 'blkid'), subprocess.TimeoutExpired('blkid', 2)):
            self.run.side_effect = error
            self.rejected()

    def test_missing_probe_tool_and_duplicate_probe_fields(self):
        self.run.side_effect = FileNotFoundError('mock missing blkid')
        self.rejected()
        self.run.side_effect = None
        self.run.return_value = SimpleNamespace(stdout='LABEL=BOOT\nTYPE=vfat\nLABEL=BOOT\n')
        self.rejected()

    def test_hotplug_and_mount_race_during_probe(self):
        def replaced(args, **kw):
            result = self.probe(args, **kw)
            self.put(self.sd / 'diskseq', '43')
            return result
        self.run.side_effect = replaced
        self.rejected()
        def mounted(args, **kw):
            result = self.probe(args, **kw)
            self.rows.append('4 1 9:3 / /new rw - ext4 /dev/alias rw')
            self.mounts()
            return result
        self.run.side_effect = mounted
        self.rejected()

    def test_unreadable_or_malformed_activity(self):
        for data in ('', 'not mountinfo'):
            self.put(self.proc / 'self/mountinfo', data)
            self.rejected()
        self.mounts()
        self.put(self.proc / 'swaps', '')
        self.rejected()

    def test_rule_preserves_system_and_ignore_precedence(self):
        rules = (REPO / 'steamos-overlay/usr/lib/udev/rules.d/98-steamos-arm-system-disk.rules').read_text()
        self.assertLess(rules.index('is-system-disk'), rules.index('is-old-system-card'))
        line = next(x for x in rules.splitlines() if 'ENV{ID_FS_USAGE}=="filesystem"' in x)
        self.assertIn('ENV{UDISKS_IGNORE}!="1"', line)
        for script in ('apply-overlays.sh', 'apply-overlays-sm8750.sh'):
            self.assertIn('is-old-system-card" "$R/usr/lib/steamos-arm/is-old-system-card" 0755',
                          (REPO / 'scripts' / script).read_text())


if __name__ == '__main__':
    unittest.main()
