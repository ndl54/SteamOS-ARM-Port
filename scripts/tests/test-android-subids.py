#!/usr/bin/env python3
"""Subordinate-ID regression tests: temporary files and mocked accounts only."""
import fcntl
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / 'sm8650-overlay/usr/lib/konkr/android-subids'
MODULE = runpy.run_path(str(HELPER), run_name='subids_test')
plan = MODULE['plan']
update = MODULE['update']
main = MODULE['main']


class SubidsTests(unittest.TestCase):
    def test_growth_custom_alias_and_idempotence(self):
        for owner in ['steamos', '1000', '01000']:
            original = f'# custom\nother:800000:65536\n{owner}:200000:65536\n'
            new = plan(original, 1000, {0, 1000})
            self.assertEqual(new, original.replace(':65536\n', ':131072\n')
                             .replace('other:800000:131072', 'other:800000:65536'))
            self.assertEqual(plan(new, 1000, {0, 1000}), new)
        enough = 'steamos:400000:262144\nother:100000:65536\n'
        self.assertEqual(plan(enough, 1000, {0, 1000}), enough)

    def test_collision_does_not_relocate(self):
        for other in ['other:165536:65536', 'other:99999:2', 'other:231071:1']:
            with self.subTest(other=other), self.assertRaises(ValueError):
                plan(f'steamos:100000:65536\n{other}\n', 1000, {1000})
        self.assertIn('131072', plan('steamos:100000:65536\nother:231072:100\n', 1000, {1000}))
        with self.assertRaises(ValueError):
            plan('steamos:100000:131072\nother:200000:1\n', 1000, {1000})

    def test_malformed_missing_multiple_and_overflow(self):
        for value in ['', 'other:100000:65536\n', 'steamos:x:65536\n',
                      'steamos:100000:-1\n', 'steamos:0:131072\n',
                      'steamos:100000:0\n', 'steamos:4294901760:65536\n',
                      'steamos:4294836224:1\n', 'steamos:100000:65536\nbad\n',
                      'steamos:100000:65536\n1000:300000:65536\n',
                      'steamos:100000:131072\nsteamos:400000:131072\n']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan(value, 1000, {1000})
        self.assertIn('131072', plan('steamos:4294836223:1\n', 1000, {1000}))
        for host_id in [100000, 200000, 231071]:
            with self.assertRaises(ValueError):
                plan('steamos:100000:65536\n', 1000, {host_id})

    def files(self, root):
        for name in ['subuid', 'subgid']:
            path = root / name
            path.write_text('steamos:100000:65536\n')
            path.chmod(0o640)

    def test_two_files_preflight_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.files(root)
            original = (root / 'subuid').read_bytes()
            (root / 'subgid').write_text('steamos:100000:65536\nother:170000:65536\n')
            with self.assertRaises(ValueError):
                update(root, 1000, {1000}, {1000})
            self.assertEqual((root / 'subuid').read_bytes(), original)
            self.files(root)
            update(root, 1000, {1000}, {1000})
            before = {p: p.stat().st_mtime_ns for p in [root / 'subuid', root / 'subgid']}
            update(root, 1000, {1000}, {1000})
            for path, mtime in before.items():
                self.assertEqual(path.read_text(), 'steamos:100000:131072\n')
                self.assertEqual(path.stat().st_mode & 0o777, 0o640)
                self.assertEqual(path.stat().st_uid, os.geteuid())
                self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_missing_symlink_and_hardlink_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.files(root)
            (root / 'subgid').unlink()
            with self.assertRaises(FileNotFoundError):
                update(root, 1000, {1000}, {1000})
            (root / 'subgid').symlink_to(root / 'subuid')
            with self.assertRaises(ValueError):
                update(root, 1000, {1000}, {1000})
            (root / 'subgid').unlink()
            os.link(root / 'subuid', root / 'subgid')
            with self.assertRaises(ValueError):
                update(root, 1000, {1000}, {1000})
            self.assertEqual((root / 'subuid').read_text(), 'steamos:100000:65536\n')

    def test_staging_failure_no_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.files(root)
            with patch.object(MODULE['os'], 'fsync', side_effect=OSError('mock full disk')):
                with self.assertRaises(OSError):
                    update(root, 1000, {1000}, {1000})
            for name in ['subuid', 'subgid']:
                self.assertEqual((root / name).read_text(), 'steamos:100000:65536\n')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['.pwd.lock', 'subgid', 'subuid'])

    def test_partial_publish_is_retryable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.files(root)
            replace = os.replace
            def fail_second(src, dst):
                if dst.name == 'subgid':
                    raise OSError('mock second rename failure')
                replace(src, dst)
            with patch.object(MODULE['os'], 'replace', side_effect=fail_second):
                with self.assertRaises(OSError):
                    update(root, 1000, {1000}, {1000})
            self.assertEqual((root / 'subuid').read_text(), 'steamos:100000:131072\n')
            self.assertEqual((root / 'subgid').read_text(), 'steamos:100000:65536\n')
            update(root, 1000, {1000}, {1000})
            self.assertEqual((root / 'subgid').read_text(), 'steamos:100000:131072\n')

    def test_locked_account_database_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.files(root)
            with (root / '.pwd.lock').open('w') as lock:
                fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                code = ("import pathlib,runpy,sys; "
                        "m=runpy.run_path(sys.argv[1],run_name='test'); "
                        "m['update'](pathlib.Path(sys.argv[2]),1000,{1000},{1000})")
                result = subprocess.run(['python3', '-B', '-c', code, str(HELPER), tmp],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('BlockingIOError', result.stderr)
            for name in ['subuid', 'subgid']:
                self.assertEqual((root / name).read_text(), 'steamos:100000:65536\n')

    def test_account_and_provider_failures_before_update(self):
        # All account queries and /etc reads are mocked; main never writes host files.
        with patch.dict(main.__globals__, update=lambda *args: self.fail('unexpected update')):
            with patch.object(MODULE['os'], 'geteuid', return_value=501):
                with self.assertRaises(ValueError): main()
            with patch.object(MODULE['os'], 'geteuid', return_value=0):
                for failure in [KeyError('missing'), OSError('NSS failed')]:
                    with patch.object(MODULE['pwd'], 'getpwnam', side_effect=failure):
                        with self.assertRaises(type(failure)): main()
                with patch.object(MODULE['pwd'], 'getpwnam', return_value=SimpleNamespace(pw_uid=0)):
                    with self.assertRaises(ValueError): main()
                with patch.object(MODULE['pwd'], 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)):
                    with patch.object(Path, 'read_text', return_value='subid : sss\n'):
                        with self.assertRaises(ValueError): main()

    def test_actual_account_uid_and_primary_groups(self):
        account = SimpleNamespace(pw_uid=1500, pw_gid=1600)
        others = [account, SimpleNamespace(pw_uid=2000, pw_gid=170000)]
        with patch.object(MODULE['os'], 'geteuid', return_value=0), \
             patch.object(MODULE['pwd'], 'getpwnam', return_value=account) as lookup, \
             patch.object(MODULE['pwd'], 'getpwall', return_value=others), \
             patch.object(MODULE['grp'], 'getgrall', return_value=[SimpleNamespace(gr_gid=1600)]), \
             patch.object(Path, 'read_text', return_value='subid: files\n'):
            calls = []
            with patch.dict(main.__globals__, update=lambda *args: calls.append(args)):
                main()
            lookup.assert_called_once_with('steamos')
            self.assertEqual(calls, [(Path('/etc'), 1500, {1500, 2000}, {1600, 170000})])
            with patch.object(MODULE['pwd'], 'getpwall', side_effect=OSError('NSS error')):
                with self.assertRaises(OSError): main()
            with patch.object(MODULE['grp'], 'getgrall', return_value=[]):
                with self.assertRaises(ValueError): main()

    def test_exact_source_relocation_regression(self):
        source = subprocess.check_output(['git', 'show',
            'b19966cf11ce4b6d38eedd99bb90b33870207c43:sm8650-overlay/usr/lib/konkr/android-subids'],
            cwd=ROOT, text=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['subuid', 'subgid']:
                (root / name).write_text('steamos:100000:65536\nother:165536:65536\n')
            # macOS sed lacks GNU's -i spelling. Only that deletion is stubbed.
            stub = root / 'sed'
            stub.write_text('#!/usr/bin/env python3\nimport pathlib,sys\n'
                            'p=pathlib.Path(sys.argv[-1])\n'
                            'p.write_text("".join(x for x in p.read_text().splitlines(True) if not x.startswith("steamos:")))\n')
            stub.chmod(0o755)
            source = source.replace('/etc/subuid /etc/subgid', '"$FIXTURE/subuid" "$FIXTURE/subgid"')
            subprocess.run(['sh', '-c', source], env={**os.environ, 'FIXTURE': tmp,
                           'PATH': tmp + os.pathsep + os.environ['PATH']}, check=True, capture_output=True)
            self.assertIn('steamos:231072:131072', (root / 'subuid').read_text())
            # That changes existing container ID 1 from host 100000 to 231072.
            self.assertNotIn('steamos:100000:', (root / 'subuid').read_text())


if __name__ == '__main__':
    unittest.main()
