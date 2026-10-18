#!/usr/bin/env python3
"""Extract CARD and partition lookup; fake commands/files only, never an installer."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
SOURCE = (REPO / 'scripts/gen5/install-gen5.sh').read_text()
CARD = SOURCE.split("<<'CARD'\n", 1)[1].split('\nCARD\n', 1)[0]
STORAGE = (REPO / 'external-and-mods/baldur/switch-to-steamos/storage.sh').read_text()
MOCK = r'''
import hashlib, os, shutil, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
base = Path(os.environ['BASE'])
with (base / 'calls').open('a') as out: out.write(name + '\n')
for arg in args:
    if arg.startswith('/'):
        assert Path(arg).is_relative_to(base), arg
mode = os.environ.get('FAIL', '')
if name == mode or (mode == 'cp+umount' and name in ('cp', 'umount')):
    sys.exit(37 if name != 'umount' else 41)
if name == 'cp': shutil.copyfile(*args)
elif name == 'mv': Path(args[0]).rename(args[1])
elif name == 'sha256sum':
    digest = hashlib.sha256(Path(args[0]).read_bytes()).hexdigest()
    if mode == 'readback-hash' and args[0].endswith('.new'): sys.exit(37)
    if mode == 'partial-hash':
        print(digest + '  ' + args[0])
        sys.exit(37)
    if mode == 'bad-hash' and args[0].endswith('.new'): digest = '0' * 64
    if mode == 'empty-hash': digest = ''
    print(digest + '  ' + args[0])
elif name == 'rmdir': Path(args[0]).rmdir()
elif name == 'umount':
    # Model the mount disappearing without deleting the backing card data.
    for path in Path(args[0]).iterdir(): path.rename(base / ('saved-' + path.name))
elif name not in ('mount', 'sync'): raise SystemExit('unexpected command')
'''


class CardStage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gen5-card-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin), BASE=str(self.base))
        for key in ('BASH_ENV', 'ENV', 'FAIL'):
            self.env.pop(key, None)
        for name in ('grep', 'sed', 'cut', 'cat', 'mktemp'):
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ('mount', 'umount', 'cp', 'mv', 'sha256sum', 'rmdir', 'sync'):
            path = self.bin / name
            path.write_text('#!' + sys.executable + '\n' + MOCK)
            path.chmod(0o755)
        for path, content in {
            'sys/class/block/a_logs/uevent': 'PARTNAME=steamos-gen5-logs\nDEVNAME=a_logs\n',
            'sys/class/block/b_root/uevent': 'PARTNAME=steamos-gen5\nDEVNAME=b_root\n',
            'sys/class/block/z_other/uevent': 'PARTNAME=unrelated\nDEVNAME=z_other\n',
            'sys/class/block/a_logs/partition': '1\n',
            'sys/class/block/b_root/partition': '2\n',
            'disk/device/type': 'SD\n',
            'dev/block/a_logs': 'ordinary mock node',
            'dev/block/b_root': 'ordinary mock node',
            'data/local/tmp/firmware.tar': 'firmware fixture',
            'data/local/tmp/android-boot.sha256': 'android hash fixture',
        }.items():
            p = self.base / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        # Actual discovery/hash primitives; only redirect paths/block predicate.
        storage = STORAGE.split('parent() {', 1)[0].replace('[ -b ', '[ -f ')
        storage += '\nparent() { printf "%s\\n" ' + shlex.quote(str(self.base / 'disk')) + '; }\n'
        storage += 'unused() { [ "${FAIL:-}" != unused ] || fail "target in use"; }\n'
        storage_path = self.base / 'data/adb/steamos-gen5/storage.sh'
        storage_path.parent.mkdir(parents=True)
        storage_path.write_text(self.redirect(storage))

    def redirect(self, script):
        for prefix in ('/sys/', '/dev/', '/data/'):
            script = script.replace(prefix, str(self.base) + prefix)
        return script

    def run_card(self, shell, mode=''):
        self.env['FAIL'] = mode
        script = self.base / 'card-fixture.sh'
        script.write_text(self.redirect(CARD))
        return subprocess.run([shell, str(script)], env=self.env, capture_output=True, timeout=10)

    def calls(self):
        path = self.base / 'calls'
        return path.read_text().splitlines() if path.exists() else []

    def test_match_followed_by_nonmatch_succeeds(self):
        result = self.run_card('/bin/dash')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(self.calls().count('mount'), 1)
        self.assertEqual(self.calls().count('umount'), 1)

    def test_errors_never_publish_success(self):
        for shell in ('/bin/dash', '/bin/bash'):
            for mode in ('mount', 'cp', 'sha256sum', 'readback-hash', 'partial-hash', 'empty-hash', 'bad-hash', 'mv', 'sync', 'umount', 'rmdir', 'cp+umount', 'unused'):
                with self.subTest(shell=shell, mode=mode):
                    case = CardStage()
                    case.setUp()
                    try:
                        result = case.run_card(shell, mode)
                        self.assertNotEqual(result.returncode, 0, result.stdout.decode())
                        if mode in ('sha256sum', 'readback-hash', 'partial-hash', 'empty-hash', 'bad-hash', 'cp'):
                            self.assertNotIn('mv', case.calls())
                        if mode in ('umount', 'cp+umount'):
                            self.assertNotIn('rmdir', case.calls())
                            self.assertIn(b'mount retained', result.stderr)
                        if mode in ('cp', 'cp+umount'):
                            self.assertEqual(result.returncode, 37)
                            self.assertIn(b'card stage failed (37): copy', result.stderr)
                        if mode in ('sha256sum', 'readback-hash', 'partial-hash', 'empty-hash'):
                            self.assertIn(b'cannot hash card copy', result.stderr)
                    finally:
                        case.doCleanups()

    def test_duplicate_or_missing_label_stops_before_mount(self):
        extra = self.base / 'sys/class/block/z_other/uevent'
        for content in ('PARTNAME=steamos-gen5-logs\nDEVNAME=a_logs\n', ''):
            if not content:
                (self.base / 'sys/class/block/a_logs/uevent').write_text('PARTNAME=other\n')
            extra.write_text(content)
            result = self.run_card('/bin/dash')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'ambiguous/missing', result.stderr)
            self.assertNotIn('mount', self.calls())


if __name__ == '__main__':
    unittest.main()
