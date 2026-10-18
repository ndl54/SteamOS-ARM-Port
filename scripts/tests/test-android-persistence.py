#!/usr/bin/env python3
"""Temporary scripts/data and mocked package commands only; never starts Android."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('focus', Path(__file__).with_name('test-android-focus.py'))
focus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(focus)
APK = focus.APK
ROOT = focus.ROOT
BEFORE = subprocess.check_output(['git', 'show', 'b691dd5d75ccac5713d05cfeaeefaaa03944d560:sm8650-overlay/usr/bin/konkr-apk'], cwd=ROOT, text=True)
SOURCE = subprocess.check_output(['git', 'show', '6b256e621cf1764bb66889758f1bc42aaf13c364:sm8650-overlay/usr/bin/konkr-apk'], cwd=ROOT, text=True)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class Persistence(unittest.TestCase):
    def test_upgrade_source_regression_and_repeated_restart(self):
        for old_loop in (True, False):
            with self.subTest(old_loop=old_loop), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); focus.fixture(root)
                p = root / 'liblepton/mounting.sh'
                if old_loop:
                    p.write_text(p.read_text().replace('"${LEPTON_OVERLAY}" "${GUESTOS_OVERLAY}"', '${LEPTON_OVERLAY} ${GUESTOS_OVERLAY}'))
                focus.apply(root, BEFORE)
                before_upgrade = snapshot(root)
                # Exact upstream adds disabled but never removes the installed split block.
                focus.apply(root, SOURCE)
                self.assertIn('--cgroups=split', p.read_text())
                self.assertIn('--cgroups=disabled', p.read_text())
                # Restore the actually deployed050 state before testing the
                # repaired upgrade (the source-only reproduction is isolated).
                for name, data in before_upgrade.items():
                    (root / name).write_bytes(data)
                focus.apply(root)
                self.assertNotIn('--cgroups=split', p.read_text())
                self.assertEqual(p.read_text().count('--cgroups=disabled'), 1)
                self.assertEqual(p.read_text().count('--ulimit stack=-1:-1'), 1)
                self.assertEqual(p.read_text().count('# konkr-apk: extra overlay'), 1)
                self.assertEqual((root / 'liblepton/properties.sh').read_text().count('# konkr-apk: certified identity'), 1)
                mounting = p.read_text()
                start = mounting.index('    # konkr-apk: low mmap layout for LuaJIT\n')
                end = mounting.index('    fi\n', start) + len('    fi\n')
                block = mounting[start:end]
                p.write_text(mounting.replace(block, block + block))
                focus.apply(root)
                self.assertEqual(p.read_text(), mounting)
                saved = snapshot(root)
                for _ in range(3):
                    self.assertEqual(focus.apply(root).stderr, '')
                    self.assertEqual(snapshot(root), saved)

    def test_cleanup_preserves_data_and_default_cleanup_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); focus.fixture(root); focus.apply(root)
            block = (root / 'liblepton/liblepton.sh').read_text() + '    fi\n'
            for prefix, value, keep in [('context', 'true', True), ('context', 'false', False), ('context', '', False), ('', 'false', True)]:
                # Symlinked ordinary temp directory models a relocated data tree.
                data = root / 'relocated data'; data.mkdir(exist_ok=True)
                link = root / 'data'
                if not link.exists(): link.symlink_to(data, target_is_directory=True)
                sentinel = data / 'account-and-installed-app'; sentinel.write_text('keep bytes')
                mode = sentinel.stat().st_mode
                code = 'prepare_baked_data_for_removal() { rm -f "$PWD/data/account-and-installed-app"; }\n' + block
                r = focus.shell(code, tmp, LEPTON_PREFIX=prefix, LEPTON_NO_CLEANUP=value)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(sentinel.exists(), keep)
                self.assertTrue(link.is_symlink())
                if keep:
                    self.assertEqual(sentinel.read_text(), 'keep bytes')
                    self.assertEqual(sentinel.stat().st_mode, mode)

    def test_unknown_critical_signatures_publish_nothing(self):
        for name, text in [('liblepton/liblepton.sh', '# unknown cleanup\n'), ('liblepton/mounting.sh', '# unknown mounting\n')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); focus.fixture(root)
                (root / name).write_text(text)
                saved = snapshot(root)
                r = subprocess.run(['python3', '-B', '-', tmp], input=focus.patcher(APK), text=True, capture_output=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('Android was not started', r.stderr)
                self.assertEqual(snapshot(root), saved)
        # Explicit daemon guard remains effective even under a conditional caller.
        with tempfile.TemporaryDirectory() as tmp:
            guard = next(x for x in APK.splitlines() if x.startswith('  patch_lepton ||'))
            r = focus.shell('patch_lepton() { return 3; }; die() { exit 1; }\nf() {\n' + guard + '\ntouch launched\n}\nif f; then :; fi', tmp)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((Path(tmp) / 'launched').exists())

    def test_partial_publication_retry_preserves_symlinks_mode_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); focus.fixture(root)
            target = root / 'actual-lepton'; (root / 'lepton').rename(target)
            (root / 'lepton').symlink_to(target)
            target.chmod(0o751); before = target.stat()
            data = root / 'user data'; data.write_text('account and APK bytes')
            code = focus.patcher(APK)
            injection = '''
real_replace = os.replace
replaces = 0
def fail_second(src, dst):
    global replaces
    replaces += 1
    if replaces == 2:
        raise OSError("mock publication failure")
    real_replace(src, dst)
os.replace = fail_second
'''
            code = code.replace('root = pathlib.Path', injection + '\nroot = pathlib.Path', 1)
            r = subprocess.run(['python3', '-B', '-', tmp], input=code, text=True, capture_output=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('mock publication failure', r.stderr)
            self.assertTrue((root / 'lepton').is_symlink())
            self.assertIn('# konkr-apk', target.read_text())
            self.assertFalse(list(root.rglob('*.konkr-*')))
            focus.apply(root)
            after = target.stat()
            self.assertEqual((before.st_mode, before.st_uid, before.st_gid), (after.st_mode, after.st_uid, after.st_gid))
            self.assertEqual(data.read_text(), 'account and APK bytes')
            saved = snapshot(root); focus.apply(root); self.assertEqual(snapshot(root), saved)

    def test_install_success_failures_and_session_abandon(self):
        body = 'cmd_install() (' + APK.split('cmd_install() (', 1)[1].split('\n)\n', 1)[0] + '\n)\n'
        mocks = r'''
APK_INFO=unused
say() { :; }; die() { echo "$*" >&2; exit 1; }
realpath() { echo "$PWD/source.apk"; }
mktemp() { mkdir "$PWD/stage"; echo "$PWD/stage"; }
unpack() { printf base >"$2/base.apk"; printf split >"$2/split.apk"; }
# Bash 3 portability shim; apk-info itself is not under test here.
mapfile() { meta=(com.test 'Fixture app'); cat >/dev/null; }
python3() { printf 'com.test\nFixture app\n'; }
stat() { echo 4; }
ensure_android() { echo ensure >>trace; }
add_title() { echo title >>trace; }
asx() {
  echo "$1" >>trace
  case "$1" in
    'cmd_real package install-create '*)
      case "$MODE" in
        missing) return 127 ;; createfail) echo 'Success: created install session [7]'; return 4 ;;
        malformed) echo 'Failure [7]' ;; *) echo 'Success: created install session [7]' ;;
      esac ;;
    'cmd_real package install-write '*)
      cat >/dev/null
      case "$MODE" in
        signal) kill -TERM "$$"; echo Success ;;
        writefail) return 3 ;; writeerror) echo 'Failure [bad split]' ;;
        *) echo 'Success: streamed 4 bytes' ;;
      esac ;;
    'cmd_real package install-commit '*)
      case "$MODE" in
        commitfail) return 5 ;; commiterror) echo 'Failure [bad session]' ;;
        *) echo Success; touch installed ;;
      esac ;;
  esac
}
'''
        for mode in ('ok', 'missing', 'createfail', 'malformed', 'writefail', 'writeerror', 'commitfail', 'commiterror', 'signal'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); (root / 'source.apk').write_text('input untouched')
                (root / 'old-app-data').write_text('old user data')
                code = mocks + body + 'if cmd_install source.apk; then exit 0; else exit 9; fi'
                if mode == 'signal':
                    # Run the extracted subshell body as its own test shell so
                    # $$ names only that disposable shell, never a real service.
                    code = mocks + 'set -- source.apk\n' + body.split('cmd_install() (', 1)[1].rsplit(')', 1)[0]
                r = focus.shell(code, tmp, MODE=mode)
                self.assertEqual(r.returncode, 0 if mode == 'ok' else (1 if mode == 'signal' else 9), r.stderr)
                trace = (root / 'trace').read_text()
                self.assertNotIn('pm install-', trace)
                self.assertEqual('install-abandon 7' in trace, mode in ('writefail', 'writeerror', 'commitfail', 'commiterror', 'signal'))
                self.assertEqual((root / 'installed').exists(), mode == 'ok')
                self.assertEqual('title\n' in trace, mode == 'ok')
                self.assertFalse((root / 'stage').exists())
                self.assertEqual((root / 'source.apk').read_text(), 'input untouched')
                self.assertEqual((root / 'old-app-data').read_text(), 'old user data')

    def test_split_title_icon_and_android_launcher_fallback(self):
        mocks = r'''
SYS="$PWD/sys"; DESKTOP_DIR="$PWD/desktop"; APK_INFO=unused; pkg=com.test
mapfile() { meta=(com.test 'Fixture app' ''); cat >/dev/null; }
mktemp() { echo "$PWD/extracted.apk"; }
python3() { if [[ "$(cat "$2")" == split ]]; then printf '\211PNG\r\n\032\nfixture' >"$3"; fi; }
steam_add() { echo "$*" >>trace; }; say() { :; }
asx() {
  echo "$1" >>trace
  case "$1" in
    'pm path '*) printf 'package:/base.apk\npackage:/split.apk\n' ;;
    "cat '/base.apk'") echo base ;;
    "cat '/split.apk'") echo split ;;
    'cmd package resolve-activity '*)
      if [[ "$MODE" == launcher ]]; then echo com.test/.Main; else echo 'No activity found'; fi ;;
  esac
}
'''
        for mode in ('launcher', 'none'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                r = focus.shell(mocks + focus.function('add_title') + 'add_title com.test', tmp, MODE=mode)
                self.assertEqual(r.returncode, 0, r.stderr)
                root = Path(tmp)
                self.assertEqual((root / 'sys/icons/com.test.png').read_bytes(), b'\x89PNG\r\n\x1a\nfixture')
                self.assertFalse((root / 'extracted.apk').exists())
                desktop = root / 'desktop/konkr-android-com.test.desktop'
                self.assertEqual(desktop.exists(), mode == 'launcher')
                if desktop.exists():
                    self.assertIn('Name=Fixture app', desktop.read_text())
                    self.assertIn('Exec=/usr/bin/konkr-apk run com.test', desktop.read_text())


if __name__ == '__main__':
    unittest.main()
