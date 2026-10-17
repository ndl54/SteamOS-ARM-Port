#!/usr/bin/env python3
"""Local control-flow regressions. No network, mounts, service, updater CLI or build.
Only inert files in TemporaryDirectory; OS effects are fail-closed mocks.
"""
import copy
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack, redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)  # __main__ entrypoints never run; use python -B.
    return module


A = load('agent048', 'steamos-overlay/usr/lib/steamos-arm/update-agent')
U = load('updater048', 'external-and-mods/konkr-update/konkr-update.py')
DATA = b'target bytes'
HASH = hashlib.sha256(DATA).hexdigest()
MANIFEST = dict(format=2, architecture='aarch64', version='1.4',
                devices=['AYANEO Pocket EVO'], kind='delta', blobs=[],
                inventory={'root/usr/bin/test': {'f': [493, 0, 0, len(DATA), HASH, {}]}},
                **{'from': ['1.3']})
MISMATCH = 'DELTA_MISMATCH: ' + json.dumps({'target': U.target_identity(MANIFEST)})


def response(code=0, error=''):
    return NS(returncode=code, stderr=error, stdout='')


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        # Any unexpected external effect is a test failure.
        self.stack.enter_context(patch('subprocess.run', side_effect=AssertionError('external process')))
        self.stack.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('network')))
        self.stack.enter_context(patch.object(U, 'run', side_effect=AssertionError('OS command')))
        self.stack.enter_context(patch.object(os, 'sync', create=True))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.stack.enter_context(patch.object(A, 'RUN', self.tmp / 'run'))
        self.stack.enter_context(patch.object(A, 'CACHE', self.tmp / 'cache'))
        self.stack.enter_context(patch('shutil.disk_usage', return_value=NS(free=10 << 30)))

    def local(self, name, data=DATA, full=False):
        p = self.tmp / name
        p.write_bytes(data)
        return dict(path=str(p), version='1.4', full=full, source='drive', size=len(data))

    def apply_fixture(self, responses, fallback=True, download_error=None):
        cand = self.local('delta.sau')
        full = self.local('full.sau', full=True)
        if fallback:
            cand['fallback'] = full
        A.CACHE.mkdir(mode=0o700)
        sentinel = A.CACHE / 'steamos-arm-sm8550-1.4.sau'
        sentinel.write_text('earlier download')
        with patch.object(A, 'status', return_value=dict(version='1.3', soc='sm8550')), \
             patch.object(A, 'newest', return_value=cand), \
             patch('subprocess.run', side_effect=responses) as proc:
            if download_error:
                with patch.object(A, 'download', side_effect=download_error):
                    code = A.apply()
            else:
                code = A.apply()
        self.assertEqual(sentinel.read_text(), 'earlier download')
        self.assertEqual(list(A.CACHE.iterdir()), [sentinel])
        self.assertEqual(Path(cand['path']).read_bytes(), DATA)
        self.assertEqual(Path(full['path']).read_bytes(), DATA)
        self.assertEqual(json.loads((A.RUN / 'result').read_text())['code'], code)
        if code:
            self.assertNotEqual(json.loads((A.RUN / 'progress').read_text())['phase'], 'done')
        return code, proc

    def test_fallback_success_binds_full_to_delta(self):
        code, proc = self.apply_fixture([response(9, MISMATCH), response()])
        self.assertEqual(code, 0)
        args = proc.call_args_list[1].args[0]
        self.assertIn('--require-full', args)
        self.assertIn('--expected-version', args)
        self.assertIn('1.4', args)
        self.assertEqual(args[-2:], ['--expected-target', U.target_identity(MANIFEST)])

    def test_delta_success_does_not_download_full(self):
        code, proc = self.apply_fixture([response()])
        self.assertEqual((code, proc.call_count), (0, 1))

    def test_fallback_stage_failure_is_failure(self):
        code, proc = self.apply_fixture([response(9, MISMATCH), response(1, 'boot copy failed')])
        self.assertEqual((code, proc.call_count), (1, 2))

    def test_fallback_download_failure_is_failure(self):
        code, proc = self.apply_fixture([response(9, MISMATCH)], download_error=['', 'checksum mismatch'])
        self.assertEqual((code, proc.call_count), (1, 1))

    def test_fallback_copy_exception_is_failure(self):
        code, proc = self.apply_fixture([response(9, MISMATCH)], download_error=['', OSError('disk full')])
        self.assertEqual((code, proc.call_count), (1, 1))

    def test_no_fallback_when_unavailable(self):
        code, proc = self.apply_fixture([response(9, MISMATCH)], fallback=False)
        self.assertEqual((code, proc.call_count), (1, 1))

    def test_only_typed_missing_blobs_retry(self):
        for code, msg in [(1, 'this system differs'), (1, 'signature differs'),
                          (1, 'not enough space'), (9, 'DELTA_MISMATCH: {}'),
                          (9, 'DELTA_MISMATCH: {"target": "bad"}'), (1, MISMATCH)]:
            with self.subTest(msg=msg), patch('subprocess.run', return_value=response(code, msg)):
                err, target = A.stage(self.tmp / 'unused', '1.4')
                self.assertTrue(err)
                self.assertEqual(target, '')

    def test_incomplete_pending_not_success(self):
        with patch.object(A, 'status', return_value={'stage_failed': True, 'staged': True}):
            self.assertEqual(A.apply(), 1)

    def test_selection_same_version_drive_precedence_and_full(self):
        delta = self.local('delta')
        full = self.local('full', full=True)
        old_full = dict(full, version='1.3.5')
        online = dict(delta, source='github')
        with patch.object(A, 'media_candidates', return_value=[delta, old_full]), \
             patch.object(A, 'github_candidates', return_value=[dict(full, source='github'), online]):
            best = A.newest('1.3', 'sm8550')
            self.assertEqual(best['path'], delta['path'])
            self.assertEqual(best['fallback']['version'], best['version'])
        with patch.object(A, 'media_candidates', return_value=[full]), \
             patch.object(A, 'github_candidates', return_value=[online]):
            self.assertTrue(A.newest('1.3', 'sm8550')['full'])
        with patch.object(A, 'media_candidates', return_value=[delta]), \
             patch.object(A, 'github_candidates', return_value=[old_full]):
            self.assertNotIn('fallback', A.newest('1.3', 'sm8550'))

    def test_github_discovery_filters_soc_and_finds_split_full(self):
        delta = 'steamos-arm-sm8550-1.4.sau'
        full = 'steamos-arm-sm8550-1.4-full.sau'
        names = [delta, full + '.001', full + '.002', full + '.sha256',
                 'steamos-arm-sm8250-1.4-full.sau']
        releases = [{'assets': [{'name': n, 'browser_download_url': 'https://invalid/' + n,
                                'size': 5} for n in names]},
                    {'draft': True, 'assets': [{'name': full, 'browser_download_url': 'unused'}]}]
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(releases).encode())):
            found = A.github_candidates('sm8550')
        self.assertEqual(len(found), 2)
        self.assertFalse(found[0]['full'])
        self.assertTrue(found[1]['full'])
        self.assertEqual(found[1]['size'], 10)
        self.assertEqual(len(found[1]['parts']), 2)

    def test_remote_full_uses_whole_checksum(self):
        cand = dict(source='github', version='1.4', full=True, parts=['first', 'second'],
                    part_sizes=[3, len(DATA)-3], size=len(DATA), sha256_url='fake-sha')
        pkg = self.tmp / 'copy'
        def fetch(url, fh, *args):
            fh.write(DATA[:3] if url == 'first' else DATA[3:])
        with patch.object(A, 'fetch', side_effect=fetch), \
             patch('urllib.request.urlopen', return_value=io.BytesIO(HASH.encode())):
            self.assertEqual(A.download(cand, pkg, 42, 40), '')
        self.assertEqual(pkg.read_bytes(), DATA)


    def test_split_names_and_soc(self):
        base = 'steamos-arm-sm8550-1.4-full.sau'
        names = [base + '.002', base + '.001', 'steamos-arm-sm8250-1.4.sau.001']
        self.assertEqual(A.split_sets(names, 'sm8550'), {base: sorted(names[:2])})
        self.assertEqual(A.split_sets([base + '.002'], 'sm8550'), {})
        self.assertTrue(A.NAME.match(base)['full'])

    def test_split_checksum_and_download_space(self):
        cand = self.local('joined-full.sau', full=True)
        parts = [self.local('part1', DATA[:3])['path'], self.local('part2', DATA[3:])['path']]
        cand['parts'] = parts
        pkg = self.tmp / 'copy'
        self.assertIn('without', A.download(cand, pkg, 0, 70))
        sha = Path(cand['path'] + '.sha256')
        sha.write_text(HASH + '  file\n')
        self.assertEqual(A.download(cand, pkg, 0, 70), '')
        self.assertEqual(pkg.read_bytes(), DATA)
        sha.write_text('0' * 64)
        self.assertIn('checksum', A.download(cand, pkg, 0, 70))
        pkg.unlink()
        with patch('shutil.disk_usage', return_value=NS(free=0)):
            self.assertIn('space', A.download(cand, pkg, 0, 70))
        self.assertFalse(pkg.exists())

    def test_private_cache_rejects_symlink_and_writable(self):
        cand = self.local('delta')
        with patch.object(A, 'status', return_value={}), patch.object(A, 'newest', return_value=cand):
            A.CACHE.symlink_to(self.tmp, target_is_directory=True)
            self.assertEqual(A.apply(), 1)
            A.CACHE.unlink()
            A.CACHE.mkdir(mode=0o777)
            A.CACHE.chmod(0o777)
            self.assertEqual(A.apply(), 1)
        self.assertEqual(list(A.CACHE.iterdir()), [])

    def test_target_integrity(self):
        full = copy.deepcopy(MANIFEST)
        full.update(kind='full', blobs=[HASH], **{'from': []})
        identity = U.target_identity(MANIFEST)
        U.check_target(full, '1.4', identity, True)
        for key, value in [('version', '1.5'), ('devices', ['AYN Odin 2']),
                           ('architecture', 'x86_64'), ('inventory', {}),
                           ('blobs', []), ('kind', 'delta')]:
            bad = copy.deepcopy(full)
            bad[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                U.check_target(bad, '1.4', identity, True)

    def stage_fixture(self, manifest, *, low='', corrupt=False, signature=False, unmount=False, boot_fail=False):
        work = self.tmp / 'work'; work.mkdir()
        pkg = work / 'package.tar.gz'; pkg.write_bytes(b'inert')
        home = self.tmp / 'home'; home.mkdir()
        boot = self.tmp / 'boot'; boot.mkdir(); (boot / 'KERNEL').write_bytes(b'old')
        cmd = self.tmp / 'cmdline'; cmd.write_text('root=UUID=test')
        pending = self.tmp / 'pending'
        paths = {'/home': home, '/boot': boot, '/proc/cmdline': cmd}
        path_factory = lambda p: paths.get(str(p), Path(p))
        plan = {k: [] for k in ('mkdir', 'write', 'link', 'whiteout', 'meta', 'delete')}
        plan['write'] = list(manifest['inventory'])
        effects = []

        def extract(*args):
            (work / 'manifest.json').write_text(json.dumps(manifest))
            (work / 'manifest.sig').write_text('fake signature')

        def command(*args, **kwargs):
            effects.append(args[0])
            if args[0] == 'umount' and unmount:
                raise OSError('busy mount')
            if args[0] == 'tar':
                p = work / 'blobs' / HASH[:2] / HASH
                p.parent.mkdir(parents=True)
                p.write_bytes(b'corrupt' if corrupt else DATA)
            elif args[0] not in ('mount', 'umount'):
                raise AssertionError(args)

        def kernel(src, dst, *args):
            dst.write_bytes(DATA)

        def install(*args):
            effects.append('install')
            if boot_fail: raise OSError('boot copy failed')

        copy2 = shutil.copy2
        with ExitStack() as stack:
            stack.enter_context(patch('shutil.copy2', side_effect=lambda src, dst: copy2(
                boot / 'KERNEL' if str(src) == '/boot/KERNEL' else src, dst)))
            for name, value in dict(Path=path_factory, extract_members=extract,
                                   verify_signature=Mock(side_effect=ValueError('signature') if signature else None),
                                   make_plan=lambda *a: copy.deepcopy(plan), run=command,
                                   backup_plan=lambda *a: effects.append('backup'),
                                   write_json=lambda p, v: Path(p).write_text(json.dumps(v)),
                                   recovery_runtime=lambda *a: effects.append('runtime'),
                                   retarget_kernel=kernel, install_kernel=install).items():
                stack.enter_context(patch.object(U, name, value))
            stack.enter_context(patch('shutil.disk_usage', side_effect=lambda p: NS(free=0 if str(p) == low else 10 << 30)))
            try:
                U.stage2(work, pkg, {'uuid':'root'}, {'uuid':'home'}, {'uuid':'boot'},
                         'AYANEO Pocket EVO', pending, '1.4', '', manifest['kind'] == 'full')
                error = None
            except Exception as exc:
                error = exc
        return error, effects, work, pending

    def test_missing_delta_is_typed_after_unmount(self):
        err, effects, work, pending = self.stage_fixture(MANIFEST)
        self.assertIsInstance(err, U.DeltaMismatch)
        self.assertEqual(effects, ['mount', 'umount'])
        self.assertFalse((work / 'rootview').exists())
        self.assertFalse(pending.exists())

    def test_full_stages_only_after_checks(self):
        full = dict(MANIFEST, kind='full', blobs=[HASH])
        err, effects, work, pending = self.stage_fixture(full)
        self.assertIsNone(err)
        self.assertTrue(pending.exists())
        self.assertFalse((work / 'staging-incomplete').exists())
        self.assertEqual(effects, ['mount', 'tar', 'backup', 'umount', 'runtime'])

    def test_home_space_fails_before_extract(self):
        err, effects, _, pending = self.stage_fixture(dict(MANIFEST, kind='full', blobs=[HASH]), low='/home')
        self.assertIn('HOME space', str(err))
        self.assertEqual(effects, ['mount', 'umount'])
        self.assertFalse(pending.exists())

    def test_root_space_fails_before_backup(self):
        err, effects, _, pending = self.stage_fixture(dict(MANIFEST, kind='full', blobs=[HASH]), low='/')
        self.assertIn('system partition', str(err))
        self.assertNotIn('backup', effects)
        self.assertFalse(pending.exists())

    def test_content_hash_failure_prevents_backup(self):
        err, effects, _, pending = self.stage_fixture(dict(MANIFEST, kind='full', blobs=[HASH]), corrupt=True)
        self.assertIn('damaged update', str(err))
        self.assertNotIn('backup', effects)
        self.assertFalse(pending.exists())

    def test_signature_failure_precedes_mount(self):
        err, effects, _, _ = self.stage_fixture(MANIFEST, signature=True)
        self.assertIn('signature', str(err))
        self.assertEqual(effects, [])

    def test_board_failure_precedes_mount(self):
        err, effects, _, _ = self.stage_fixture(dict(MANIFEST, devices=['AYN Odin 2']))
        self.assertIn('not AYANEO Pocket EVO', str(err))
        self.assertEqual(effects, [])

    def test_unmount_failure_suppresses_retry(self):
        err, effects, work, pending = self.stage_fixture(MANIFEST, unmount=True)
        self.assertNotIsInstance(err, U.DeltaMismatch)
        self.assertTrue((work / 'rootview').exists())
        self.assertFalse(pending.exists())

    def test_boot_failure_retains_incomplete_marker(self):
        full = copy.deepcopy(MANIFEST)
        full.update(kind='full', blobs=[HASH])
        full['inventory']['boot/KERNEL'] = full['inventory']['root/usr/bin/test']
        err, effects, work, pending = self.stage_fixture(full, boot_fail=True)
        self.assertIn('boot copy failed', str(err))
        self.assertTrue(pending.exists())
        self.assertTrue((work / 'staging-incomplete').exists())

    def test_cleanup_owns_only_unmounted_uncommitted_work(self):
        pending = self.tmp / 'pending'
        work = self.tmp / 'transaction'; work.mkdir()
        view = work / 'rootview'; view.mkdir()
        sentinel = view / 'system-file'; sentinel.write_text('keep')
        with self.assertRaisesRegex(RuntimeError, 'retained transaction'):
            U.discard_failed_stage(work, pending)
        self.assertEqual(sentinel.read_text(), 'keep')
        sentinel.unlink(); view.rmdir()
        pending.write_text('transaction')
        with self.assertRaisesRegex(RuntimeError, 'retained transaction'):
            U.discard_failed_stage(work, pending)
        self.assertTrue(work.is_dir())
        pending.unlink()
        U.discard_failed_stage(work, pending)
        self.assertFalse(work.exists())

    def test_status_distinguishes_failed_stage(self):
        pending = self.tmp / 'pending'
        base = self.tmp / 'transactions'; base.mkdir()
        work = base / 'txn'; work.mkdir()
        mapping = {'/' + U.PENDING: pending, '/home/.konkr-updates': base}
        with patch.object(U, 'Path', side_effect=lambda p: mapping[str(p)]):
            self.assertEqual(U.pending_status(), {'staged': False, 'stage_failed': False})
            pending.write_text('txn\n')
            self.assertEqual(U.pending_status(), {'staged': True, 'stage_failed': False})
            (work / 'staging-incomplete').touch()
            self.assertEqual(U.pending_status(), {'staged': False, 'stage_failed': True})

    def test_planner_checks_live_hash_and_preserves_identity(self):
        root = self.tmp / 'root'; home = self.tmp / 'home'; boot = self.tmp / 'boot'
        live = root / 'usr/bin/test'; live.parent.mkdir(parents=True); live.write_bytes(DATA)
        preserved = root / 'etc/hostname'; preserved.parent.mkdir(); preserved.write_text('custom')
        target = copy.deepcopy(MANIFEST['inventory'])
        target['root/usr/bin/test']['f'][:3] = [live.stat().st_mode & 0o777, os.getuid(), os.getgid()]
        with patch.object(U, 'xattrs_of', return_value={}):
            self.assertEqual(U.make_plan(target, root, home, boot)['write'], [])
            live.write_bytes(b'changed data')
            plan = U.make_plan(target, root, home, boot)
        self.assertEqual(plan['write'], ['root/usr/bin/test'])
        self.assertNotIn('root/etc/hostname', plan['delete'])



if __name__ == '__main__':
    unittest.main(verbosity=2)
