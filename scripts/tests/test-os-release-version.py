#!/usr/bin/env python3
"""Release-label/rollback regressions on temp files; no services or real updates."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


L = load('label052', ROOT / 'steamos-overlay/usr/lib/steamos-arm/os-release-version')
U = load('updater052', Path(os.environ.get('UPDATER_UNDER_TEST',
    ROOT / 'external-and-mods/konkr-update/konkr-update.py')))
BASE = ('NAME="SteamOS"\nID=steamos\nPRETTY_NAME="SteamOS"\nVERSION="Frame 0.5.3"\n'
        'VERSION_ID=0.5.3\nBUILD_ID=20261001\nVARIANT_ID=steamdeck\n'
        '# custom settings\nCUSTOM="keep me"\n')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = self.temp / 'root'
        self.root.mkdir()
        self.stack.enter_context(patch('subprocess.run', side_effect=AssertionError('external command')))
        self.stack.enter_context(patch.object(os, 'sync', create=True))
        self.stack.enter_context(patch.object(os, 'listxattr', return_value=[], create=True))
        self.stack.enter_context(patch.object(U, 'Progress'))  # never open device logs
        self.stack.enter_context(patch.object(U, 'install_kernel', side_effect=AssertionError('boot write')))
        self.osr = self.write('etc/os-release', BASE)
        self.inventory = self.write(L.INVENTORY, json.dumps({'version': '1.3', 'soc': 'sm8550', 'files': {}}))

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def label(self, version='1.3'):
        self.assertIn(f'PRETTY_NAME="Unofficial SteamOS ARM {version}"\n', self.osr.read_text())
        self.assertEqual(self.osr.read_text().replace(f'Unofficial SteamOS ARM {version}', 'SteamOS'), BASE)

    def test_preserves_identity_custom_keys_mode_and_idempotence(self):
        self.osr.chmod(0o640)
        before = self.osr.stat()
        L.label_release(self.root)
        self.label()
        st = self.osr.stat()
        self.assertEqual(st.st_mode & 0o777, 0o640)
        self.assertEqual((st.st_uid, st.st_gid), (before.st_uid, before.st_gid))
        L.label_release(self.root)
        self.assertEqual(self.osr.stat().st_mtime_ns, st.st_mtime_ns)

    def test_missing_malformed_and_wrong_type_inventory(self):
        for data in ('not json', '[]', 'null', '{"version": 123}', '{"version": ["1.3"]}',
                     '{"version": "1.3\\nBAD=yes"}', '{"version": "١.٣"}', '{}'):
            with self.subTest(data=data):
                self.inventory.write_text(data)
                L.label_release(self.root)
                self.assertEqual(self.osr.read_text(), BASE)
        self.inventory.unlink()
        L.label_release(self.root)
        self.assertEqual(self.osr.read_text(), BASE)

    def test_pending_and_failed_stage_do_not_promote_target(self):
        L.label_release(self.root)
        self.inventory.write_text('{"version": "1.4"}')
        pending = self.write(L.PENDING, 'test-transaction\n')
        for state in ('backed-up', 'applying', 'rolling-back'):
            self.write('home/.konkr-updates/test-transaction/state.json', json.dumps({'state': state}))
            self.write('home/.konkr-updates/test-transaction/staging-incomplete', '')
            L.label_release(self.root)
            self.label()
        pending.unlink()
        L.label_release(self.root)
        self.label('1.4')

    def test_relative_and_absolute_image_symlinks(self):
        for link in ('../usr/lib/os-release', '/usr/lib/os-release'):
            with self.subTest(link=link):
                self.osr.unlink()
                vendor = self.write('usr/lib/os-release', BASE)
                self.osr.symlink_to(link)
                L.label_release(self.root)
                self.assertFalse(self.osr.is_symlink())
                self.label()
                self.assertEqual(vendor.read_text(), self.osr.read_text())

    def test_external_link_never_reads_or_writes_host(self):
        outside = self.temp / 'outside'
        outside.write_text('HOST SENTINEL\n')
        self.osr.unlink()
        self.osr.symlink_to(outside)
        L.label_release(self.root)
        self.assertTrue(self.osr.is_symlink())
        self.assertEqual(outside.read_text(), 'HOST SENTINEL\n')

    def test_parent_links_are_resolved_in_image(self):
        self.osr.unlink()
        self.osr.parent.rmdir()
        (self.root / 'etc').symlink_to('/config')
        self.write('config/os-release', BASE)
        L.label_release(self.root)
        self.assertIn('Unofficial SteamOS ARM 1.3', (self.root / 'config/os-release').read_text())

    def test_image_upper_and_final_inventory_hash(self):
        upper = self.write('var/lib/overlays/etc/upper/os-release', BASE)
        self.inventory.unlink()
        L.label_release(self.root, '1.4')
        self.label('1.4')
        self.assertEqual(upper.read_text(), self.osr.read_text())
        target = {'root/etc/os-release': U.entry_for(self.osr)}
        U.record_inventory(self.root, self.root / 'home', target, version='1.4')
        self.assertEqual(U.recorded(self.root)['root/etc/os-release'][2], U.digest(self.osr))
        self.assertEqual(U.recorded_release(self.root)['version'], '1.4')

    def test_duplicate_label_and_missing_label_preserve_other_text(self):
        self.osr.write_text(BASE + 'PRETTY_NAME="old duplicate"\n')
        L.label_release(self.root)
        self.label()
        self.osr.write_text('ID=steamos\nCUSTOM=keep')
        L.label_release(self.root)
        self.assertEqual(self.osr.read_text(), 'ID=steamos\nCUSTOM=keep\nPRETTY_NAME="Unofficial SteamOS ARM 1.3"\n')

    def test_fixed_tmp_symlink_is_untouched(self):
        outside = self.temp / 'outside'
        outside.write_text('sentinel')
        self.osr.with_suffix('.tmp').symlink_to(outside)
        L.label_release(self.root)
        self.label()
        self.assertEqual(outside.read_text(), 'sentinel')

    def test_failed_atomic_publish_preserves_original(self):
        with patch.object(L.os, 'replace', side_effect=OSError('publication failure')):
            with self.assertRaises(OSError):
                L.label_release(self.root)
        self.assertEqual(self.osr.read_text(), BASE)
        self.assertEqual(list(self.osr.parent.glob('.os-release-*')), [])

    def test_symlink_loop_fails_without_writes(self):
        self.osr.unlink()
        self.osr.symlink_to('os-release')
        with self.assertRaises(ValueError):
            L.label_release(self.root)
        self.assertTrue(self.osr.is_symlink())

    def transaction(self, kernel=False):
        work = self.temp / 'work'
        work.mkdir()
        plan = {k: [] for k in ('mkdir', 'write', 'link', 'whiteout', 'meta', 'delete')}
        if kernel:
            plan['write'] = ['boot/KERNEL']
        U.write_json(work / 'plan.json', plan)
        U.write_json(work / 'target.json', {})
        U.write_json(work / 'transaction.json', {'version': '1.4'})
        U.backup_plan(plan, self.root, self.root / 'home', work)
        pending = self.write(L.PENDING, 'test-transaction\n')
        return work, pending

    def test_recovery_commits_new_release(self):
        work, pending = self.transaction()
        self.assertEqual(U.recover2(self.root, self.temp / 'boot', self.root / 'home',
                                   work, pending, 'backed-up'), 0)
        self.assertEqual(json.loads((work / 'state.json').read_text())['state'], 'committed')
        self.assertFalse(pending.exists())
        L.label_release(self.root)
        self.label('1.4')

    def test_failed_apply_restores_inventory_and_old_release(self):
        original = self.inventory.read_bytes()
        work, pending = self.transaction(kernel=True)
        with patch.object(U, 'install_kernel', side_effect=[OSError('kernel write failed'), None]):
            self.assertEqual(U.recover2(self.root, self.temp / 'boot', self.root / 'home',
                                       work, pending, 'backed-up'), 10)
        self.assertEqual(self.inventory.read_bytes(), original)
        self.assertEqual(json.loads((work / 'state.json').read_text())['state'], 'rolled-back')
        self.assertFalse(pending.exists())
        L.label_release(self.root)
        self.label()

    def test_rollback_request_restores_old_inventory(self):
        original = self.inventory.read_bytes()
        work, pending = self.transaction()
        U.apply2(self.root, self.temp / 'boot', self.root / 'home', work)
        with patch.object(U, 'install_kernel'):
            self.assertEqual(U.recover2(self.root, self.temp / 'boot', self.root / 'home',
                                       work, pending, 'rollback-requested'), 10)
        self.assertEqual(self.inventory.read_bytes(), original)
        L.label_release(self.root)
        self.label()

    def test_legacy_transaction_discards_unknown_new_inventory(self):
        work, pending = self.transaction()
        U.write_json(work / 'backup-index.json', {})
        self.inventory.write_text('{"version": "1.4"}')
        with patch.object(U, 'install_kernel'):
            U.recover2(self.root, self.temp / 'boot', self.root / 'home', work, pending, 'applying')
        self.assertFalse(self.inventory.exists())
        L.label_release(self.root)
        self.assertEqual(self.osr.read_text(), BASE)

    def test_pre_inventory_image_rollback_removes_new_record(self):
        self.inventory.unlink()
        work, pending = self.transaction()
        U.apply2(self.root, self.temp / 'boot', self.root / 'home', work)
        with patch.object(U, 'install_kernel'):
            U.recover2(self.root, self.temp / 'boot', self.root / 'home', work, pending, 'applying')
        self.assertFalse(self.inventory.exists())


if __name__ == '__main__':
    unittest.main()
