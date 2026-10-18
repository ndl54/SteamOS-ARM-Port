#!/usr/bin/env python3
"""Extracted host adapter only: private files, strict fake ADB, no installer/device."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[2]
SOURCE = (REPO / 'scripts/gen5/install-gen5.sh').read_text()
# Stop before the first remote mutation; never execute the installer body.
PREFIX = SOURCE.split('su_ "mkdir -p $D && chmod 700 $D && mkdir $D/operation.lock"')[0]
PUSHES = [line for line in SOURCE.splitlines() if line.startswith('push ')]
MOCK = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps(args) + '\n')
if args[:1] == ['-s']:
    assert args[1] == os.environ.get('ANDROID_SERIAL', 'tablet-123')
    args = args[2:]
elif args != ['get-serialno']:
    raise SystemExit('unbound tablet call')
mode = os.environ.get('FAIL', '')
values = {
    ('get-serialno',): os.environ.get('ANDROID_SERIAL', 'tablet-123'),
    ('get-state',): 'device',
    ('shell', 'getprop', 'ro.product.model'): 'TB323FU',
    ('shell', 'getprop', 'ro.product.device'): 'baldur',
    ('shell', 'getprop', 'ro.build.display.id'): '18.0.12.104',
    ('shell', "su -c 'id'"): 'uid=0(root)',
    ('shell', "su -c 'rmdir /data/adb/steamos-gen5/operation.lock'"): '',
    ('shell', "su -c 'sh /data/local/tmp/sg5-card.sh'"): '',
}
if args == ['exec-out', 'binary-probe']:
    sys.stdout.buffer.write(b'\x00\xff\r\nraw\rbytes')
elif args[:1] == ['push']:
    assert len(args) >= 3 and args[-1].startswith('/data/local/tmp/')
    expected = 'C:\\' if Path(sys.argv[0]).suffix.lower() == '.exe' else '/'
    assert all(p.startswith(expected) for p in args[1:-1])
elif tuple(args) in values:
    value = values[tuple(args)]
    if mode == 'unknown' and args == ['get-serialno']: value = 'unknown'
    if mode == 'offline' and args == ['get-state']: value = 'offline'
    sys.stdout.buffer.write((value + os.environ.get('EOL', '\r\n')).encode())
else:
    raise SystemExit('forbidden mock command: ' + repr(args))
if mode and mode in ' '.join(args):
    raise SystemExit(23)
'''
WSLPATH = r'''
import os, sys
from pathlib import Path
assert sys.argv[1] == '-w' and Path(sys.argv[2]).is_absolute()
with open(os.environ['CONVERSIONS'], 'a') as f: f.write(sys.argv[2] + '\n')
if os.environ.get('CONVERT_FAIL', '') in ('all', Path(sys.argv[2]).name):
    print('partial output')
    raise SystemExit(29)
if os.environ.get('CONVERT_FAIL') == 'empty': raise SystemExit(0)
print('C:' + sys.argv[2].replace('/', '\\'))
'''


class HostADB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gen5 host ' Việt $ ` ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.release = self.base / 'release'
        self.release.mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.calls = self.base / 'calls'
        self.conversions = self.base / 'conversions'
        self.env = dict(os.environ, PATH=str(self.bin), CALLS=str(self.calls),
                        CONVERSIONS=str(self.conversions), TMPDIR=str(self.base))
        for name in ('ADB', 'ANDROID_SERIAL', 'BASH_ENV', 'ENV', 'FAIL', 'CONVERT_FAIL'):
            self.env.pop(name, None)
        # PATH cannot fall through to a real adb/wslpath or mutation command.
        for name in ('dirname', 'mktemp', 'rm', 'tr', 'grep', 'tar'):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / 'python3').symlink_to(sys.executable)
        for name in ('Image-gen5', 'firmware.tsv', 'boot-repack.py',
                     'switch-to-steamos/action.sh', 'switch-to-steamos/storage.sh'):
            path = self.release / name
            path.parent.mkdir(exist_ok=True)
            path.write_text('fixture')

    def executable(self, name, body):
        path = self.bin / name
        path.write_text('#!' + sys.executable + '\n' + body)
        path.chmod(0o755)
        return path

    def setup_adb(self, name='adb'):
        path = self.executable(name, MOCK)
        if name.lower().endswith('.exe'):
            self.executable('wslpath', WSLPATH)
        return path

    def run_host(self, body='', args=(), success=True):
        script = self.release / 'adapter-fixture.sh'
        script.write_text(PREFIX + '\n' + body + '\n')
        result = subprocess.run(['/bin/bash', str(script), *args], env=self.env,
                                capture_output=True, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr.decode())
        else:
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list(self.release.glob('.work.*')))
        return result

    def log(self):
        return [json.loads(x) for x in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_native_discovery_no_recursion_all_pushes_and_lf(self):
        self.setup_adb()
        self.env['EOL'] = '\n'
        self.run_host('\n'.join(PUSHES))
        self.assertEqual(sum('push' in x for x in self.log()), 6)
        self.assertFalse(self.conversions.exists())

    def test_windows_discovery_crlf_every_local_source_only(self):
        self.setup_adb('adb.exe')
        self.run_host('\n'.join(PUSHES))
        pushes = [x for x in self.log() if 'push' in x]
        self.assertEqual(len(pushes), 6)
        self.assertEqual(len([p for x in pushes for p in x[3:-1]]), 7)
        for args in pushes:
            self.assertEqual(args[:3], ['-s', 'tablet-123', 'push'])
            self.assertTrue(all("Việt" in x and "'" in x for x in args[3:-1]))
        self.assertNotIn('/data/', self.conversions.read_text())

    def test_explicit_executable_spaces_unicode_uppercase_suffix_and_serial(self):
        path = self.setup_adb('My Việt ADB.EXE')
        self.env.update(ADB=str(path), ANDROID_SERIAL='chosen-456')
        self.run_host('\n'.join(PUSHES))
        self.assertEqual(self.log()[0], ['get-serialno'])
        self.assertTrue(all(x[:2] == ['-s', 'chosen-456'] for x in self.log()[1:]))

    def test_native_preferred_over_windows(self):
        self.setup_adb('adb.exe')
        self.setup_adb()
        self.run_host(PUSHES[0])
        self.assertFalse(self.conversions.exists())

    def test_missing_or_invalid_adb_stops_before_calls(self):
        self.run_host(success=False)
        self.env['ADB'] = str(self.base / 'missing adb')
        self.run_host(success=False)
        self.assertEqual(self.log(), [])

    def test_missing_wslpath_and_conversion_failure_stop_before_calls(self):
        self.setup_adb('adb.exe')
        (self.bin / 'wslpath').unlink()
        self.run_host(success=False)
        self.executable('wslpath', WSLPATH)
        for mode in ('all', 'empty'):
            self.env['CONVERT_FAIL'] = mode
            self.run_host(success=False)
        self.assertEqual(self.log(), [])

    def test_failed_or_empty_conversion_never_calls_push(self):
        self.setup_adb('adb.exe')
        for mode in ('firmware.tar', 'empty'):
            self.run_host('export CONVERT_FAIL=' + shlex.quote(mode) + '\n' + PUSHES[1], success=False)
        self.assertFalse(any('push' in x for x in self.log()))

    def test_read_error_even_with_valid_stdout_stops(self):
        self.setup_adb()
        for mode in ('get-serialno', 'unknown', 'get-state', 'offline',
                     'ro.product.model', 'ro.product.device', 'ro.build.display.id', "su -c 'id'"):
            with self.subTest(mode=mode):
                self.env['FAIL'] = mode
                self.run_host(PUSHES[0], success=False)
        self.assertFalse(any('push' in x for x in self.log()))

    def test_push_failure_keeps_exit_status(self):
        self.setup_adb('adb.exe')
        self.env['FAIL'] = 'push'
        result = self.run_host(PUSHES[0] + '\necho SHOULD_NOT_RUN', success=False)
        self.assertEqual(result.returncode, 23)
        self.assertNotIn(b'SHOULD_NOT_RUN', result.stdout)
        self.assertIn(b'ERROR: stopped at line', result.stderr)

    def test_error_diagnostics_in_functions_substitutions_and_pipelines(self):
        for name in ('adb', 'adb.exe'):
            self.env['ADB'] = str(self.setup_adb(name))
            for body in ('broken() { return 37; }; broken',
                         'value="$(exit 37)"', '(exit 37) | tr -d x'):
                with self.subTest(name=name, body=body):
                    result = self.run_host(body + '\necho SHOULD_NOT_RUN', success=False)
                    self.assertEqual(result.returncode, 37)
                    self.assertIn(b'ERROR: stopped at line', result.stderr)
                    self.assertNotIn(b'ERROR:', result.stdout)
                    self.assertNotIn(b'SHOULD_NOT_RUN', result.stdout)

    def test_binary_output_is_not_crlf_filtered(self):
        self.setup_adb('adb.exe')
        out = self.base / 'binary'
        self.run_host('adb exec-out binary-probe > ' + shlex.quote(str(out)))
        self.assertEqual(out.read_bytes(), b'\x00\xff\r\nraw\rbytes')

    def test_card_failure_stops_before_success_even_after_lock_cleanup(self):
        line = next(x for x in SOURCE.splitlines() if x.startswith('su_ "sh /data/local/tmp/sg5-card.sh"'))
        for name in ('adb', 'adb.exe'):
            self.env['ADB'] = str(self.setup_adb(name))
            self.env['FAIL'] = 'sg5-card.sh'
            result = self.run_host('locked=1\n' + line + '\necho SHOULD_NOT_RUN', success=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b'could not stage firmware on the card', result.stderr)
            self.assertNotIn(b'SHOULD_NOT_RUN', result.stdout)
            self.assertIn('operation.lock', self.log()[-1][-1])

    def test_cleanup_failure_and_prior_status(self):
        self.setup_adb()
        self.env['FAIL'] = 'rmdir'
        for status in (0, 37):
            result = self.run_host(f'locked=1\nexit {status}', success=False)
            self.assertEqual(result.returncode, status or 1)
            self.assertIn(b'Remote lock retained', result.stderr)

    def test_switch_alias_and_invalid_args(self):
        self.setup_adb()
        for args, expected in (((), 0), (('--switch',), 1), (('-switch',), 1)):
            self.run_host(f'[[ $SWITCH == {expected} ]]', args=args)
        for args in (('--typo',), ('--switch', 'extra')):
            self.run_host(args=args, success=False)

    def test_archive_path_is_data_not_python_source(self):
        # Exercise only the actual archive expression with two tiny fixture files.
        # This is not installer packaging, image creation or boot repacking.
        line = next(x for x in SOURCE.splitlines() if 'shutil.make_archive' in x)
        (self.base / 'module').mkdir()
        (self.base / 'module/action.sh').write_text('fixture')
        result = subprocess.run(['/bin/bash', '-eu', '-c',
                                 'W=' + shlex.quote(str(self.base)) + '\n' + line],
                                env=self.env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        with zipfile.ZipFile(self.base / 'switch-to-steamos.zip') as archive:
            self.assertEqual(archive.read('action.sh'), b'fixture')


if __name__ == '__main__':
    unittest.main()
