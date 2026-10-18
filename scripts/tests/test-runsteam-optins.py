#!/usr/bin/env python3
"""Only extracted launcher policies, temporary files and inert command sinks."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = 'steamos-overlay/usr/share/deckard/RUNSTEAM.sh'
TEXT = (REPO / LAUNCHER).read_text()
SOURCE = '0ed40ff7203c2646d7015af0cef3594680e740be'
DEFAULTS = (b'BootStrapperInhibitAll=enable\n'
            b'BootStrapperForceSelfUpdate=disable\n'
            b'BootStrapperInhibitClientChecksum=enable\n'
            b'BootStrapperInhibitBootstrapperChecksum=enable\n'
            b'BootStrapperInhibitUpdateOnLaunch=enable\n')


def embedded(tag):
    return TEXT.split("<<'" + tag + "'", 1)[1].split('\n', 1)[1].split('\n' + tag, 1)[0]


def fake_elf(path, machine=183, payload=b'native-v1'):
    header = bytearray(20)
    header[:6] = b'\x7fELF\x02\x01'
    header[18:20] = machine.to_bytes(2, 'little')
    path.write_bytes(header + payload)
    path.chmod(0o755)


class Optins(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="steam 'root ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rt = self.root / 'steamrtarm64'
        self.rt.mkdir()
        (self.root / 'steamrt64').mkdir()
        self.client = self.rt / 'streaming_client'
        self.backup = self.rt / 'streaming_client.arm64'
        self.x86 = self.root / 'steamrt64/streaming_client'
        self.flag = self.root / '.pyrowave-box64'
        fake_elf(self.client)
        fake_elf(self.x86, 62)
        self.original = self.client.read_bytes()

    def config(self, allow='0'):
        with patch.object(sys, 'argv', ['cfg', str(self.root), self.rt.name, allow]):
            exec(embedded('STEAM_CFG'), {})

    def setup(self, box=True):
        access = os.access
        with patch.object(sys, 'argv', ['setup', str(self.root), self.rt.name]), \
             patch('shutil.which', return_value='/fake/box64' if box else None), \
             patch('os.access', side_effect=lambda p, m: False if str(p) == '/usr/local/bin/box64' else access(p, m)):
            exec(embedded('PYROWAVE_SETUP'), {})

    def test_default_and_optin_preserve_custom_config_in_both_locations(self):
        custom = b'# choice\r\nForceChannel=beta\r\nCustomKey=hello\r\n'
        for parent in (self.root, self.rt):
            (parent / 'steam.cfg').write_bytes(custom + DEFAULTS)
        self.config()
        self.config('1')
        for parent in (self.root, self.rt):
            self.assertEqual((parent / 'steam.cfg').read_bytes(), custom)
        self.config('0')
        for parent in (self.root, self.rt):
            self.assertEqual((parent / 'steam.cfg').read_bytes(), custom + DEFAULTS)

    def test_custom_bootstrap_value_and_mode_survive(self):
        p = self.root / 'steam.cfg'
        p.write_bytes(b'BootStrapperInhibitAll=disable\nOther=1')
        p.chmod(0o600)
        self.config()
        self.assertIn(b'BootStrapperInhibitAll=disable', p.read_bytes())
        self.assertNotIn(b'BootStrapperInhibitAll=enable', p.read_bytes())
        self.config('1')
        self.assertEqual(p.read_bytes(), b'BootStrapperInhibitAll=disable\nOther=1\n')
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_config_failure_and_symlink_do_not_truncate(self):
        p = self.root / 'steam.cfg'
        p.write_bytes(DEFAULTS + b'Custom=1\n')
        before = p.read_bytes()
        with patch('os.replace', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                self.config('1')
        self.assertEqual(p.read_bytes(), before)
        p.unlink()
        p.symlink_to(self.root / 'outside')
        with self.assertRaises(SystemExit):
            self.config()
        self.assertFalse((self.root / 'outside').exists())
        self.assertEqual(list(self.root.glob('.steam.cfg.*')), [])

    def test_flag_environment_and_argument_precedence(self):
        gate = TEXT[TEXT.index('ALLOW_CLIENT_UPDATES=0'):TEXT.index('# Preserve custom settings;')]
        args = TEXT[TEXT.index('if [[ "${IS_SIDELOAD}" == "0" ]]; then\n  STEAM_ARGS='):TEXT.index('\nSTEAM_COMMAND=')]
        for marker, env, enabled in [(False, '', False), (False, '0', False), (False, '1', True),
                                     (True, '0', True), (False, 'yes', False)]:
            p = self.root / '.allow-client-updates'
            if marker:
                p.touch()
            elif p.exists():
                p.unlink()
            script = ('set -eu\nSTEAMROOT=' + shlex.quote(str(self.root)) + '\nIS_SIDELOAD=0\n' + gate + args +
                      '\nprintf "%s\\n" "${STEAM_ARGS[@]}"')
            run = subprocess.run(['bash', '-c', script], text=True, capture_output=True,
                                 env={**os.environ, 'STEAM_ALLOW_CLIENT_UPDATES': env,
                                      'STEAM_EXTRA_ARGS': '-inhibitbootstrap -nobootstrapperupdate -noverifyfiles -custom'})
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual('-inhibitbootstrap' in run.stdout.splitlines(), not enabled)
            self.assertEqual('-nobootstrapperupdate' in run.stdout.splitlines(), not enabled)
            self.assertIn('-custom', run.stdout.splitlines())
            self.assertIn('-noverifyfiles', run.stdout.splitlines())
        # Sideload command line is explicitly supplied and remains authoritative.
        script = 'set -eu\nIS_SIDELOAD=1\nALLOW_CLIENT_UPDATES=1\njq() { echo "-inhibitbootstrap -sideload"; }\n' + args + '\nprintf "%s\\n" "${STEAM_ARGS[@]}"'
        run = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.splitlines(), ['-inhibitbootstrap', '-sideload'])

    def test_default_no_wrapper(self):
        self.setup()
        self.assertEqual(self.client.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())

    def test_enable_repeat_disable_retains_backup(self):
        self.flag.touch()
        self.setup()
        wrapper = self.client.read_bytes()
        self.assertIn(b'PYROWAVE_BOX64_WRAPPER', wrapper)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.setup()
        self.assertEqual(self.client.read_bytes(), wrapper)
        self.flag.unlink()
        self.setup()
        self.assertEqual(self.client.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)

    def test_update_replaces_backup_with_new_native(self):
        self.flag.touch()
        self.setup()
        fake_elf(self.client, payload=b'new-client')
        newer = self.client.read_bytes()
        self.setup()
        self.assertEqual(self.backup.read_bytes(), newer)
        self.setup(box=False)
        self.assertEqual(self.client.read_bytes(), newer)

    def test_missing_or_wrong_arch_prerequisites_restore(self):
        self.flag.touch()
        for machine in (183, 3):
            fake_elf(self.x86, 62)
            self.setup()
            fake_elf(self.x86, machine)
            self.setup()
            self.assertEqual(self.client.read_bytes(), self.original)
        self.x86.unlink()
        self.setup()
        self.assertEqual(self.client.read_bytes(), self.original)

    def test_unknown_script_symlink_or_wrong_native_preserved(self):
        self.flag.touch()
        for data in (b'#!/bin/sh\n# custom\n', b'not ELF'):
            self.client.write_bytes(data)
            with self.assertRaises(RuntimeError):
                self.setup()
            self.assertEqual(self.client.read_bytes(), data)
        self.client.unlink()
        self.client.symlink_to(self.x86)
        with self.assertRaises(RuntimeError):
            self.setup()
        self.assertTrue(self.client.is_symlink())

    def test_backup_failure_leaves_live_native(self):
        self.flag.touch()
        with patch('os.replace', side_effect=OSError('backup failure')):
            with self.assertRaises(OSError):
                self.setup()
        self.assertEqual(self.client.read_bytes(), self.original)
        self.assertEqual(list(self.rt.glob('.streaming-client.*')), [])

    def test_wrapper_publication_failure_leaves_live_native_and_backup(self):
        self.flag.touch()
        replace = os.replace
        def fail(src, dst):
            if dst == self.client:
                raise OSError('wrapper failure')
            replace(src, dst)
        with patch('os.replace', side_effect=fail):
            with self.assertRaises(OSError):
                self.setup()
        self.assertEqual(self.client.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(list(self.rt.glob('.streaming-client.*')), [])

    def test_missing_backup_is_reported_and_unknown_disabled_file_preserved(self):
        self.flag.touch()
        self.setup()
        self.backup.unlink()
        before = self.client.read_bytes()
        with self.assertRaises(RuntimeError):
            self.setup()
        self.assertEqual(self.client.read_bytes(), before)
        self.flag.unlink()
        with self.assertRaises(RuntimeError):
            self.setup()
        self.client.write_bytes(b'#!/bin/sh\n# unrelated\n')
        fake_elf(self.backup)
        self.setup()
        self.assertEqual(self.client.read_bytes(), b'#!/bin/sh\n# unrelated\n')

    def test_wrapper_argv_environment_exit_and_native_routing(self):
        self.flag.touch()
        self.setup()
        fakebin = self.root / 'bin'
        fakebin.mkdir()
        sink = fakebin / 'box64'
        sink.write_text('#!/bin/sh\nprintf "box=%s\\nemulated=%s\\nlibs=%s\\npreload=%s\\n" "$1" "$BOX64_EMULATED_LIBS" "$BOX64_LD_LIBRARY_PATH" "${LD_PRELOAD-unset}"\nshift\nprintf "arg=%s\\n" "$@"\nexit 17\n')
        sink.chmod(0o755)
        env = {**os.environ, 'PATH': str(fakebin) + os.pathsep + os.environ['PATH'],
               'BOX64_EMULATED_LIBS': 'custom.so', 'BOX64_LD_LIBRARY_PATH': '/custom/libs'}
        run = subprocess.run(['sh', str(self.client), 'two words', "quote'", '*'], env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 17)
        out = (self.root / 'logs/streaming_client_box64.log').read_text()
        self.assertIn('emulated=libSDL3_ttf.so.0:custom.so', out)
        self.assertIn('/linux64:/custom/libs', out)
        self.assertIn('preload=unset', out)
        self.assertIn("arg=two words\narg=quote'\narg=*\n", out)
        # Steam also exposes the runtime through ~/.steam/binarm64 (a directory symlink).
        links = self.root / 'links'
        links.mkdir()
        (links / 'binarm64').symlink_to(self.rt, target_is_directory=True)
        run = subprocess.run(['sh', str(links / 'binarm64/streaming_client'), 'linked path'], env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 17, run.stderr)
        self.assertIn('arg=linked path', (self.root / 'logs/streaming_client_box64.log').read_text())
        # Replace the never-executed ELF fixture with a harmless native command sink.
        self.backup.write_text('#!/bin/sh\nprintf "native:%s\\n" "$@"\nexit 23\n')
        self.flag.unlink()
        run = subprocess.run(['sh', str(self.client), 'native argument'], env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 23)
        self.assertEqual(run.stdout, 'native:native argument\n')

    def test_linuxarm64_fallback_layout(self):
        self.rt.rename(self.root / 'linuxarm64')
        self.rt = self.root / 'linuxarm64'
        self.client = self.rt / 'streaming_client'
        self.backup = self.rt / 'streaming_client.arm64'
        self.flag.touch()
        self.config()
        self.assertEqual((self.rt / 'steam.cfg').read_bytes(), DEFAULTS)
        self.setup()
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.flag.unlink()
        self.setup()
        self.assertEqual(self.client.read_bytes(), self.original)

    def test_backup_symlink_and_chmod_failure_preserve_native(self):
        self.flag.touch()
        target = self.root / 'unrelated'
        target.write_bytes(b'keep')
        self.backup.symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.setup()
        self.assertEqual(target.read_bytes(), b'keep')
        self.assertEqual(self.client.read_bytes(), self.original)
        self.backup.unlink()
        with patch('os.fchmod', side_effect=OSError('chmod failed')):
            with self.assertRaises(OSError):
                self.setup()
        self.assertEqual(self.client.read_bytes(), self.original)
        self.assertEqual(list(self.rt.glob('.streaming-client.*')), [])

    def test_source_regression_config_deletion(self):
        source = subprocess.check_output(['git', 'show', SOURCE + ':' + LAUNCHER], cwd=REPO, text=True)
        block = source[source.index('ALLOW_CLIENT_UPDATES=0'):source.index('# Version 0')]
        self.flag.touch()
        (self.root / '.allow-client-updates').touch()
        config = self.root / 'steam.cfg'
        config.write_bytes(b'CustomChoice=keep\n')
        run = subprocess.run(['bash', '-c', 'set -eu\nSTEAMROOT=' + shlex.quote(str(self.root)) + '\nSTEAM_RT_ARM64=steamrtarm64\n' + block])
        self.assertEqual(run.returncode, 0)
        self.assertFalse(config.exists(), 'source deletes unrelated setting')

    def test_source_regression_failed_backup_still_overwrites(self):
        source = subprocess.check_output(['git', 'show', SOURCE + ':' + LAUNCHER], cwd=REPO, text=True)
        block = source[source.index('_sc="'):source.index('echo "RUNSTEAM: DISPLAY')]
        self.flag.touch()
        script = ('set -eu\nSTEAMROOT=' + shlex.quote(str(self.root)) + '\nSTEAM_RT_ARM64=steamrtarm64\n'
                  'box64() { return 0; }\nmv() { return 1; }\n' + block)
        run = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotEqual(self.client.read_bytes(), self.original)
        self.assertFalse(self.backup.exists())
        syntax = subprocess.run(['sh', '-n', str(self.client)], capture_output=True)
        self.assertNotEqual(syntax.returncode, 0, 'source wrapper breaks on apostrophe in root')


if __name__ == '__main__':
    unittest.main()
