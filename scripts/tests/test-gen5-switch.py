#!/usr/bin/env python3
"""Action status boundary with ordinary files and private, strict command mocks."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
ACTION = (REPO / 'external-and-mods/baldur/switch-to-steamos/action.sh').read_text()
STORAGE = (REPO / 'external-and-mods/baldur/switch-to-steamos/storage.sh').read_text()
MOCK = r'''
import hashlib, os, sys
from pathlib import Path
root = Path(os.environ['FIXTURE']).resolve()
cmd = Path(sys.argv[0]).name
args = sys.argv[1:]
mode = os.environ.get('FAIL', '')
def path(x):
    p = Path(x).resolve()
    assert p.is_relative_to(root), p
    return p
with (root / 'calls').open('a') as f: f.write(cmd + ' ' + repr(args) + '\n')
if cmd == 'stat':
    assert args[:2] == ['-c', '%s']
    print(path(args[2]).stat().st_size)
elif cmd == 'sha256sum':
    p = path(args[0]); data = p.read_bytes()
    if mode == 'readback' and p.name == 'a' and (root / 'written').exists(): data = b'bad'
    print(hashlib.sha256(data).hexdigest(), args[0])
elif cmd == 'dd':
    assert len(args) == 4 and args[2:] == ['bs=4096', 'conv=fsync']
    src, dst = path(args[0][3:]), path(args[1][3:])
    step = 'write' if dst.name == 'a' else 'backup'
    if mode == step: raise SystemExit(37)
    dst.write_bytes(src.read_bytes())
    if step == 'write': (root / 'written').touch()
    if mode == 'backup_verify' and step == 'backup': dst.write_bytes(b'bad')
elif cmd == 'blockdev':
    assert len(args) == 2 and args[0] == '--flushbufs' and path(args[1]) == root / 'a'
    if mode == 'flush': raise SystemExit(37)
elif cmd == 'sync':
    assert not args
    if mode == 'sync' and (root / 'written').exists(): raise SystemExit(37)
elif cmd == 'reboot':
    assert not args
    (root / 'reboot').touch()
elif cmd == 'rmdir':
    p = path(args[0])
    if mode == 'cleanup': raise SystemExit(37)
    p.rmdir()
else: raise SystemExit('forbidden mock command')
'''


class Switch(unittest.TestCase):
    def run_action(self, shell, mode='', args=('--no-reboot',)):
        with tempfile.TemporaryDirectory(prefix='gen5-switch-') as t:
            root = Path(t)
            state = root / 'state'; state.mkdir()
            bindir = root / 'bin'; bindir.mkdir()
            for name in ('mkdir', 'mktemp', 'head', 'cat', 'cut'):
                (bindir / name).symlink_to(shutil.which(name))
            for name in ('stat', 'sha256sum', 'dd', 'blockdev', 'sync', 'reboot', 'rmdir'):
                p = bindir / name
                p.write_text('#!' + sys.executable + '\n' + MOCK); p.chmod(0o755)
            linux = b'ANDROID!' + b'L' * 504
            android = b'ANDROID!' + b'B' * 504
            (root / 'a').write_bytes(b'ANDROID!' + b'A' * 504)
            (root / 'b').write_bytes(android)
            (state / 'linux.img').write_bytes(linux)
            (state / 'linux.img.sha256').write_text(hashlib.sha256(linux).hexdigest())
            (state / 'android.sha256').write_text(hashlib.sha256(android).hexdigest())
            if mode == 'digest': (state / 'linux.img.sha256').write_text('f' * 64)
            if mode == 'size':
                (state / 'linux.img').write_bytes(linux + b'X')
                (state / 'linux.img.sha256').write_text(hashlib.sha256(linux + b'X').hexdigest())
            helper = STORAGE.split('part() {')[0] + '''
checks=0
check_boot() {
  checks=$((checks + 1))
  [ "$FAIL" != target ] || fail 'target invalid'
  [ "$FAIL:$checks" != prewrite:2 ] || fail 'target changed'
  a="$FIXTURE/a"; b="$FIXTURE/b"; sectors=1
}
'''
            (root / 'storage.sh').write_text(helper)
            script = root / 'action.sh'
            script.write_text(ACTION.replace('D=/data/adb/steamos-gen5', 'D=' + shlex.quote(str(state))))
            env = dict(os.environ, PATH=str(bindir), FIXTURE=str(root), FAIL=mode)
            env.pop('BASH_ENV', None); env.pop('ENV', None)
            result = subprocess.run([shell, str(script), *args], env=env, capture_output=True, timeout=10)
            return result, (root / 'reboot').exists(), (root / 'written').exists(), (state / 'operation.lock').exists()

    def test_preparation_success_and_default_action(self):
        for shell in ('/bin/bash', shutil.which('dash')):
            result, reboot, written, locked = self.run_action(shell)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(written); self.assertFalse(reboot); self.assertFalse(locked)
            self.assertIn(b'boot image verified', result.stdout)
            result, reboot, written, locked = self.run_action(shell, args=())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(reboot); self.assertTrue(written); self.assertFalse(locked)
            self.assertIn(b'boot completion is not verified', result.stdout)

    def test_failures_never_request_reboot_or_report_success(self):
        for shell in ('/bin/bash', shutil.which('dash')):
            for mode in ('target', 'prewrite', 'digest', 'size', 'backup', 'backup_verify',
                         'write', 'flush', 'readback', 'sync', 'cleanup'):
                with self.subTest(shell=shell, mode=mode):
                    result, reboot, written, locked = self.run_action(shell, mode)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertFalse(reboot)
                    if mode not in ('flush', 'readback', 'sync', 'cleanup'):
                        self.assertFalse(written)
                    if mode != 'cleanup': self.assertNotIn(b'boot image verified', result.stdout)
                    if mode in ('sync', 'cleanup'):
                        self.assertEqual(result.returncode, 37)
                    else:
                        diagnostic = {
                            'target': b'target invalid', 'prewrite': b'target changed',
                            'digest': b'staged SteamOS image differs', 'size': b'invalid SteamOS image',
                            'backup': b'backup failed', 'backup_verify': b'backup did not verify',
                            'write': b'write failed', 'flush': b'flush failed',
                            'readback': b'readback failed',
                        }[mode]
                        self.assertIn(diagnostic, result.stderr)

    def test_unknown_arguments_stop_before_mutation(self):
        for args in (('--typo',), ('--no-reboot', 'extra')):
            result, reboot, written, locked = self.run_action('/bin/bash', args=args)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(reboot or written or locked)


if __name__ == '__main__':
    unittest.main()
