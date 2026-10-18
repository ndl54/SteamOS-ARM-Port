#!/usr/bin/env python3
"""Ordinary-file delta cache regressions; no mounts, builds or real updater CLI."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('updater060', REPO / 'external-and-mods/konkr-update/konkr-update.py')
U = importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)
PYC = 'root/usr/lib/example/__pycache__/module.cpython-313.pyc'
DB = 'root/usr/lib/holo/pacmandb/sync/core.db'


class TransientTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root, self.home, self.boot, self.work = [self.tmp / n for n in ('root', 'home', 'boot', 'work')]
        for p in (self.root, self.home, self.boot, self.work): p.mkdir()
        for name in ('run', 'install_kernel', 'recovery_runtime'):
            self.stack.enter_context(patch.object(U, name, side_effect=AssertionError('external effect')))
        self.stack.enter_context(patch('subprocess.run', side_effect=AssertionError('external process')))
        self.stack.enter_context(patch.object(os, 'sync', create=True))
        self.stack.enter_context(patch.object(U, 'Progress'))
        self.stack.enter_context(patch.object(U, 'xattrs_of', return_value={}))

    def path(self, key):
        return U.real_path(key, self.root, self.home, self.boot)

    def fixture(self, keys=(PYC, DB)):
        for key in keys:
            p = self.path(key); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'release')
        target = U.walk_managed(lambda k: self.path(k), skip_etc=True)
        for key in keys: self.path(key).write_bytes(b'drifted')
        plan = U.make_plan(target, self.root, self.home, self.boot)
        return target, plan

    def drop(self, plan, target, blobs=()):
        U.drop_stale_transient(plan, target, set(blobs), self.root, self.home)

    def save(self, plan, target):
        U.write_json(self.work / 'plan.json', plan)
        U.write_json(self.work / 'target.json', target)
        U.write_json(self.work / 'transaction.json', {'version': '1.4'})

    def test_cache_delta_apply_and_rollback_inventory(self):
        target, plan = self.fixture()
        old = {'format': 2, 'version': '1.3', 'files': {'old': [1, 2, 'old-hash']}}
        U.write_json(self.root / U.INVENTORY, old)
        signed = copy.deepcopy(target)
        self.drop(plan, target)
        self.assertEqual(target, signed)
        self.assertEqual(plan['write'], [])
        self.assertIn(PYC, plan['delete'])
        self.assertNotIn(DB, plan['delete'])
        self.assertEqual(self.path(PYC).read_bytes(), b'drifted')  # stage only plans
        self.assertEqual(self.path(DB).read_bytes(), b'drifted')
        self.save(plan, target)
        U.backup_plan(plan, self.root, self.home, self.work)
        U.apply2(self.root, self.boot, self.home, self.work)
        self.assertFalse(self.path(PYC).exists())
        self.assertEqual(self.path(DB).read_bytes(), b'drifted')
        recorded = U.recorded(self.root)
        self.assertNotIn(DB, recorded)  # never label drifted bytes with target hash
        self.assertNotIn(PYC, recorded)
        self.assertEqual(U.recorded_release(self.root)['version'], '1.4')
        next_plan = U.make_plan(target, self.root, self.home, self.boot)
        self.assertIn(DB, next_plan['write'])
        with patch.object(U, 'install_kernel'):
            U.restore2(self.root, self.boot, self.home, self.work)
        self.assertEqual(self.path(PYC).read_bytes(), b'drifted')
        self.assertEqual(self.path(DB).read_bytes(), b'drifted')
        self.assertEqual(json.loads((self.root / U.INVENTORY).read_text()), old)

    def test_only_cache_file_names_in_managed_locations(self):
        for key in (PYC, DB, DB + '.sig', DB.replace('.db', '.files'),
                    'home/steamos/homebrew/plugins/konkr-control/__pycache__/main.cpython-313.pyc'):
            self.assertTrue(U.is_transient(key), key)
        for key in ('root/opt/app/pacmandb/sync/user.json', PYC.replace('.pyc', '.json'),
                    PYC.rsplit('/', 1)[0], DB.rsplit('/', 1)[0],
                    DB.replace('/sync/', '/local/'), DB.replace('core.db', 'config'),
                    'root/etc/__pycache__/settings.pyc', 'home/steamos/Documents/__pycache__/data.pyc',
                    DB.replace('/sync/', '/sync/../sync/')):
            self.assertFalse(U.is_transient(key), key)

    def test_missing_cache_is_omitted_without_delete(self):
        target, plan = self.fixture()
        for key in (PYC, DB): self.path(key).unlink()
        self.drop(plan, target)
        self.assertEqual(plan['write'], [])
        self.assertEqual(plan['delete'], [])

    def test_available_blobs_still_install_and_verify(self):
        target, plan = self.fixture()
        sha = target[PYC]['f'][4]
        self.drop(plan, target, [sha])
        self.assertEqual(set(plan['write']), {PYC, DB})
        self.assertEqual(plan['delete'], [])
        blob = self.work / 'blobs' / sha[:2] / sha
        blob.parent.mkdir(parents=True); blob.write_bytes(b'release')
        self.save(plan, target)
        U.apply2(self.root, self.boot, self.home, self.work)
        for key in (PYC, DB):
            self.assertEqual(self.path(key).read_bytes(), b'release')
            self.assertEqual(U.recorded(self.root)[key][2], sha)

    def test_directory_and_leaf_symlink_are_not_dropped(self):
        target, plan = self.fixture()
        p = self.path(PYC); p.unlink(); p.mkdir(); (p / 'user-data').write_text('keep')
        with self.assertRaises(ValueError): self.drop(plan, target)
        self.assertEqual((p / 'user-data').read_text(), 'keep')
        p.joinpath('user-data').unlink(); p.rmdir()
        outside = self.tmp / 'outside'; outside.write_text('keep')
        p.symlink_to(outside)
        with self.assertRaises(ValueError): self.drop(plan, target)
        self.assertEqual(outside.read_text(), 'keep')

    def test_parent_symlink_is_not_followed_for_deletion(self):
        target, plan = self.fixture()
        p = self.path(PYC); p.unlink(); p.parent.rmdir()
        outside = self.tmp / 'outside'; outside.mkdir()
        sentinel = outside / p.name; sentinel.write_text('keep')
        p.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): self.drop(plan, target)
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_user_config_and_managed_artifacts_require_blobs(self):
        keys = ('root/opt/app/pacmandb/sync/user.json', PYC.replace('.pyc', '.json'),
                'root/usr/lib/holo/pacmandb/local/pkg/desc', 'root/usr/bin/app',
                'root/etc/app.conf')
        target, plan = self.fixture(keys)
        self.drop(plan, target)
        self.assertEqual(set(plan['write']), set(keys))
        self.assertEqual(plan['delete'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
