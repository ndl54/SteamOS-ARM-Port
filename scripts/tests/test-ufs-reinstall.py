#!/usr/bin/env python3
"""Fake tables/sysfs and GUI mocks only. Never launch an installer or disk tool."""
import os
from pathlib import Path
import runpy
import stat
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
UFS = ROOT / 'external-and-mods/ufs-install'
NS = runpy.run_path(str(UFS / 'ufs-resume-check.py'))
NS = NS['check'].__globals__
PROGRESS = runpy.run_path(str(Path(__file__).with_name('test-ufs-installer-progress.py')))


def table():
    t = dict(device='/dev/sda', label='gpt', unit='sectors', sectorsize=512,
             firstlba=2048, lastlba=500000000, id='disk-id', partitions=[])
    start = 2048
    for n, (name, gib, typ) in enumerate(zip(
            ['userdata', 'ROCKNIX', 'STORAGE', 'HOME'], [32, 2, 20, 32],
            ['userdata-type', NS['PART']['TYPE_ESP'], NS['PART']['TYPE_LINUX'], NS['PART']['TYPE_LINUX']]), 1):
        size = gib * (1 << 30) // 512
        t['partitions'].append(dict(node=f'/dev/sda{n}', name=name, uuid=f'id-{n}',
                                    type=typ, start=start, size=size, attrs=''))
        start += size
    return t


class Layout(unittest.TestCase):
    def test_complete_layout_and_old_android_size(self):
        t = table()
        self.assertEqual(NS['layout'](t, '/dev/sda'), t['partitions'])
        t['partitions'][0]['size'] = 8 * (1 << 30) // 512
        NS['layout'](t, '/dev/sda')  # retry preserves even an old <16G Android
        self.assertEqual(NS['PART']['MIN_ANDROID_GIB'], 16)

    def test_reject_malformed_or_foreign_layouts(self):
        mutations = [
            lambda t: t.update(device='/dev/sdb'),
            lambda t: t.update(sectorsize=1024),
            lambda t: t['partitions'][1].update(start=2048),
            lambda t: t['partitions'][1].update(size=0),
            lambda t: t['partitions'][1].update(node='/dev/sdb2'),
            lambda t: t['partitions'][1].update(uuid='id-1'),
            lambda t: t['partitions'][2].update(name='HOME'),
            lambda t: t['partitions'][1].update(type=NS['PART']['TYPE_BASIC_DATA']),
            lambda t: t['partitions'].pop(),
            lambda t: t.update(lastlba=3000),
        ]
        for mutate in mutations:
            t = table()
            mutate(t)
            with self.subTest(t=t), self.assertRaises(ValueError):
                NS['layout'](t, '/dev/sda')

    def test_exact_board_and_soc(self):
        for compat, good in [(b'ayaneo,pocketevo\0qcom,sm8550\0', True),
                             (b'ayaneo,pocketevo-extra\0qcom,sm8550\0', False),
                             (b'ayaneo,pocketevo\0qcom,sm8650\0', False),
                             (b'lenovo,elden\0qcom,sm8750\0', False),
                             (b'ayn,odin2\0ayaneo,pocketevo\0qcom,sm8550\0', False)]:
            with self.subTest(compat=compat), patch.object(Path, 'read_bytes', return_value=compat):
                if good:
                    NS['board']()
                else:
                    with self.assertRaises(ValueError): NS['board']()


class RuntimeChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.disk = self.base / 'controller/sda'
        self.disk.mkdir(parents=True)
        (self.disk.parent / 'driver').symlink_to(self.base / 'ufshcd-qcom')
        self.t = table()
        self.paths = {'sda': self.disk}
        for n, entry in enumerate(self.t['partitions'], 1):
            p = self.disk / f'sda{n}'
            p.mkdir()
            for key, value in [('partition', n), ('start', entry['start']), ('size', entry['size'])]:
                (p / key).write_text(str(value))
            self.paths[p.name] = p

    def check(self, fingerprint=None):
        with patch.dict(NS, board=lambda: None, source_disk=lambda: self.base / 'SD',
                        device=lambda name: self.paths[name], idle=lambda disk: None), \
                patch.dict(NS['PART'], read_table=lambda disk: self.t, sh=MagicMock()):
            return NS['check']('/dev/sda', fingerprint or NS['PART']['fingerprint'](self.t))

    def test_kernel_matches_before_retry(self):
        self.assertEqual(self.check(), self.t)

    def test_stale_kernel_and_fingerprint_rejected(self):
        with self.assertRaisesRegex(ValueError, 'table changed'): self.check('f' * 16)
        (self.paths['sda3'] / 'size').write_text('1')
        with self.assertRaisesRegex(ValueError, 'stale'): self.check()

    def test_usb_target_rejected(self):
        (self.disk.parent / 'driver').unlink()
        with self.assertRaisesRegex(ValueError, 'physical Qualcomm'): self.check()

    def test_device_requires_matching_block_identity(self):
        p = self.base / 'sda'
        p.mkdir()
        (p / 'dev').write_text('8:0')
        (p / 'ro').write_text('0')
        with patch.dict(NS, SYS=self.base), patch.object(os, 'stat') as st:
            st.return_value = types.SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 0))
            self.assertEqual(NS['device']('sda'), p)
            st.return_value.st_rdev = os.makedev(8, 1)
            with self.assertRaises(ValueError): NS['device']('sda')
            st.return_value.st_mode = stat.S_IFREG
            with self.assertRaises(ValueError): NS['device']('sda')

    def test_source_must_be_direct_sd_root_and_boot(self):
        card = self.base / 'mmcblk0'
        (card / 'device').mkdir(parents=True)
        (card / 'device/type').write_text('SD')
        for name, identity in [('mmcblk0p1', '179:1'), ('mmcblk0p2', '179:2')]:
            p = card / name
            p.mkdir()
            (p / 'partition').write_text(name[-1])
            (p / 'dev').write_text(identity)
            self.paths[name] = p
            (self.base / identity).symlink_to(p)
        self.paths['mmcblk0'] = card
        real_path = Path
        def paths(*args):
            return self.base / args[1] if args[0] == '/sys/dev/block' else real_path(*args)
        for mode in ('valid', 'overlay', 'bind-root', 'emmc', 'wrong-identity'):
            (card / 'device/type').write_text('MMC' if mode == 'emmc' else 'SD')
            def findmnt(*args):
                boot = args[3] == '/boot'
                return __import__('json').dumps({'filesystems': [{
                    'maj:min': '179:1' if boot else ('179:9' if mode == 'wrong-identity' else '179:2'),
                    'fstype': 'vfat' if boot else ('overlay' if mode == 'overlay' else 'ext4'),
                    'fsroot': '/subdir' if mode == 'bind-root' else '/',
                }]})
            with self.subTest(mode=mode), patch.dict(NS, Path=paths, device=lambda name: self.paths[name]), \
                    patch.dict(NS['PART'], sh=findmnt):
                if mode == 'valid': self.assertEqual(NS['source_disk'](), card.resolve())
                else:
                    with self.assertRaises((ValueError, OSError)): NS['source_disk']()

    def test_idle_excludes_mount_swap_holders_and_loop(self):
        sysroot = self.base / 'sys'
        disk = sysroot / 'sda'
        disk.mkdir(parents=True)
        (disk / 'dev').write_text('8:0')
        (disk / 'holders').mkdir()
        original = Path.read_text
        for mode in ['idle', 'mount', 'swap', 'holder', 'loop']:
            with self.subTest(mode=mode):
                holder = disk / 'holders/dm-0'
                if mode == 'holder': holder.touch()
                elif holder.exists(): holder.unlink()
                loop = sysroot / 'loop0/loop/backing_file'
                if mode == 'loop':
                    loop.parent.mkdir(parents=True)
                    loop.write_text('/fake/backing')
                def read(p, *args, **kw):
                    if str(p) == '/proc/self/mountinfo':
                        return '1 2 8:0 / /mount rw - ext4 /dev/alias rw\n' if mode == 'mount' else ''
                    if str(p) == '/proc/swaps':
                        return 'Filename Type Size Used Priority\n' + ('/fake/swap partition 1 0 -2\n' if mode == 'swap' else '')
                    return original(p, *args, **kw)
                real_stat = os.stat
                def st(path, *args, **kw):
                    if str(path).startswith('/fake/'):
                        return types.SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 0))
                    return real_stat(path, *args, **kw)
                with patch.dict(NS, SYS=sysroot), patch.object(Path, 'read_text', read), patch.object(os, 'stat', st):
                    if mode == 'idle': NS['idle'](disk)
                    else:
                        with self.assertRaises(ValueError): NS['idle'](disk)


class UI(unittest.TestCase):
    def setUp(self):
        self.ns, self.gtk, self.glib = PROGRESS['load_gui']()
        with patch.object(self.ns['MainWindow'], 'refresh_async'):
            self.win = self.ns['MainWindow']()
        # Distinct GTK buttons; the minimal progress fixture shares its factory mock.
        self.win.install_btn = MagicMock()
        self.win.refresh_btn = MagicMock()

    def probe(self, mode, safe='0', from_sd='1', error=False):
        info = dict(MODE=mode, RESUME_SAFE=safe, RUNNING_FROM_SD=from_sd,
                    MIN_ANDROID_GIB='16', MAX_ANDROID_GIB='-10', RECOMMENDED_ANDROID_GIB='-10')
        probe = MagicMock(return_value=info, side_effect=RuntimeError('failed') if error else None)
        with patch.dict(self.ns, probe_sizes=probe), patch.object(self.ns['threading'], 'Thread') as thread:
            self.win.refresh_async()
            thread.call_args.kwargs['target']()
            self.glib.idle_add.call_args.args[0]()

    def test_retry_gate_and_size_display(self):
        for mode, safe, sd, enabled in [('fresh', '0', '1', True), ('installed', '1', '1', True),
                                      ('installed', '0', '1', False), ('occupied', '1', '1', False),
                                      ('installed', '1', '0', False)]:
            with self.subTest(mode=mode, safe=safe, sd=sd):
                self.probe(mode, safe, sd)
                self.win.install_btn.set_sensitive.assert_called_with(enabled)
                self.win.size_spin.set_range.assert_called_with(16, 16)
                if mode == 'installed':
                    self.assertIn('unchanged', self.win.linux_label.set_text.call_args.args[0])

    def test_failed_refresh_clears_previous_authority(self):
        self.probe('installed', '1')
        self.probe('installed', error=True)
        self.assertEqual(self.win._info, {})
        self.assertFalse(self.win._reinstall)
        self.win.install_btn.set_sensitive.assert_called_with(False)

    def test_reinstall_argv_and_destructive_confirmation(self):
        self.win._reinstall = True
        self.win.ack.get_active.return_value = True
        self.win.size_spin.get_value.return_value = 64
        self.win._info = {'TABLE_FINGERPRINT': '0123456789abcdef'}
        self.gtk.MessageDialog.side_effect = None
        self.gtk.MessageDialog.return_value.run.return_value = self.gtk.ResponseType.OK
        runner = MagicMock(return_value=(0, 'fake'))
        with patch.dict(self.ns, run_install=runner), patch.object(self.ns['threading'], 'Thread') as thread:
            self.win._on_install()
            thread.call_args.kwargs['target']()
        argv = runner.call_args.args[0]
        self.assertIn('--resume', argv)
        self.assertNotIn('--android-gb', argv)
        self.assertNotIn('bash', argv)
        self.assertIn('backups', self.gtk.MessageDialog.return_value.format_secondary_text.call_args.args[0])

    def test_policy_only_probe_passwordless(self):
        actions = ET.parse(UFS / 'polkit/org.steamos-arm.easy-ufs-install.policy').getroot().findall('action')
        self.assertEqual(len(actions), 2)
        for a in actions:
            self.assertEqual(a.findtext('defaults/allow_any'), 'no')
            self.assertEqual(a.findtext('defaults/allow_inactive'), 'no')
            probe = a.attrib['id'].endswith('probe')
            self.assertEqual(a.findtext('defaults/allow_active'), 'yes' if probe else 'auth_admin')
            self.assertEqual(a.findtext('annotate'), '/usr/share/easy-ufs-install/' +
                             ('ufs-probe-sizes.sh' if probe else 'install-masios-to-internal.sh'))


if __name__ == '__main__': unittest.main()
