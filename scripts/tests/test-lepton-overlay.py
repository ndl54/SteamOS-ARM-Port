#!/usr/bin/env python3
"""Source fragments with temporary files/stubs only; no build/runtime entrypoint."""
import ast
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
APK = (ROOT / 'sm8650-overlay/usr/bin/konkr-apk').read_text()
BUILD = (ROOT / 'external-and-mods/konkr-android/framework/build-framework.sh').read_text()
PATCH = APK.split("<<'EOF'\n", 1)[1].split('\nEOF', 1)[0]


def shell(code, root, **env):
    return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + code], cwd=root,
                          env={**os.environ, **env}, capture_output=True, text=True)


class LeptonReview(unittest.TestCase):
    def test_overlay_spellings_idempotence_and_unknown(self):
        calls = [n for n in ast.parse(PATCH).body if isinstance(n, ast.Expr)
                 and isinstance(n.value, ast.Call) and getattr(n.value.func, 'id', '') == 'patch']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'liblepton').mkdir()
            fixtures = {}
            for node in calls:
                name, old, _ = [ast.literal_eval(a) for a in node.value.args]
                if old not in fixtures.get(name, ''):
                    fixtures[name] = fixtures.get(name, '') + old
            fixtures['liblepton/properties.sh'] = (
                '    props_echo "ro.product.model=Lepton"\n'
                '    props_echo "ro.product.manufacturer=Valve"\n')
            for names in ('${LEPTON_OVERLAY} ${GUESTOS_OVERLAY}',
                          '"${LEPTON_OVERLAY}" "${GUESTOS_OVERLAY}"', '"${FUTURE}"'):
                with self.subTest(names=names):
                    for name, text in fixtures.items():
                        (root / name).write_text(text)
                    mount = root / 'liblepton/mounting.sh'
                    mount.write_text(mount.read_text() + f'    for OVERLAY in {names}; do\n')
                    r = subprocess.run(['python3', '-B', '-', tmp], input=PATCH,
                                       capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    first = mount.read_text()
                    unknown = 'FUTURE' in names
                    self.assertEqual('overlay loop changed' in r.stderr, unknown)
                    self.assertEqual(first.count('# konkr-apk: extra overlay'), 0 if unknown else 1)
                    again = subprocess.run(['python3', '-B', '-', tmp], input=PATCH,
                                           capture_output=True, text=True)
                    self.assertEqual(again.returncode, 0)
                    self.assertEqual(first, mount.read_text())
                    if not unknown:
                        self.assertEqual(r.stderr + again.stderr, '')
                        loop = next(x for x in first.splitlines() if 'for OVERLAY' in x)
                        # Only expand names: no mount or Lepton invocation.
                        expanded = shell(loop + '\nprintf "<%s>\\n" "$OVERLAY"\ndone', tmp,
                                         LEPTON_OVERLAY='/base', GUESTOS_OVERLAY='/guest',
                                         KONKR_LEPTON_OVERLAY='/common /framework /props')
                        self.assertEqual(expanded.stdout.splitlines(),
                                         ['</base>', '</guest>', '</common>', '</framework>', '</props>'])

    def test_exact_image_version_and_fallback(self):
        func = APK.split('overlay_dirs() {', 1)[1].split('\n}\n', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'images').mkdir()
            (root / 'lepton-v3.0.3').mkdir()
            for ver in ('v3.0.3', 'v3.0.5', ''):
                (root / 'images/version.txt').write_text(ver)
                r = shell('LEPTON_DIR="$PWD"; OVERLAY_ROOT="$PWD"\n'
                          'say() { echo "$*" >&2; }; props_overlay() { echo /props; }\n'
                          'overlay_dirs() {' + func + '\n}\noverlay_dirs', tmp)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual('/lepton-v3.0.3' in r.stdout, ver == 'v3.0.3')
                self.assertIn('/common', r.stdout)
                self.assertIn('/props', r.stdout)
                self.assertEqual('stock framework' in r.stderr, ver != 'v3.0.3')

    def test_failed_or_unrecognized_accounts_preserve_data(self):
        block = APK.split('    local accounts\n', 1)[1].split('\n  fi\n  echo "$GAMESCOPE', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            for dump, status, clear, marker in [('', '1', False, False),
                    ('permission denied', '0', False, False), ('', '0', False, False),
                    ('Accounts: 0', '0', True, True),
                    ('Accounts: 1', '0', False, True),
                    ('Accounts: 0\nAccounts: 10', '0', False, True),
                    ('Accounts: 1\nAccount {name=user, type=com.google}', '0', False, True)]:
                with self.subTest(dump=dump, status=status):
                    for name in ('props-rev', 'cleared'):
                        (Path(tmp) / name).unlink(missing_ok=True)
                    r = shell('SYS="$PWD"; PROPS_REV=2\nsay() { :; }\n'
                              'asx() { if [[ "$1" == "dumpsys account" ]]; then '
                              'printf "%s" "$DUMP"; return "$STATUS"; else touch cleared; fi; }\n'
                              + block, tmp, DUMP=dump, STATUS=status)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual((Path(tmp) / 'cleared').exists(), clear)
                    self.assertEqual((Path(tmp) / 'props-rev').exists(), marker)

    def test_framework_validation_preserves_previous_payload(self):
        block = BUILD.split('# Validate a fresh sibling', 1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / 'lepton-v3.0.3'
            for count, ssh_fail, publish_fail in [(9, '0', '0'), (10, '1', '0'),
                                                  (10, '0', '1'), (10, '0', '0')]:
                with self.subTest(count=count, ssh_fail=ssh_fail, publish_fail=publish_fail):
                    out.mkdir(exist_ok=True)
                    (out / 'old').write_text('preserve')
                    code = 'out="$PWD/lepton-v3.0.3"; tmp="$PWD/scratch"; mkdir -p "$tmp"\n'
                    code += '''SSH=(fake_ssh)
fake_ssh() { return "$SSH_FAIL"; }
# No archive/build: simulate ten ordinary output files and AppleDouble metadata.
tar() { local dest="$4" i; for ((i=0;i<COUNT;i++)); do echo fixture >"$dest/$i"; done; echo metadata >"$dest/._0"; }
mv() { if [[ "$PUBLISH_FAIL" == 1 && "$1" == *.new.* && "$1" != *.previous ]]; then return 1; fi; command mv "$@"; }
'''
                    r = shell(code + '# Validate a fresh sibling' + block, tmp,
                              COUNT=str(count), SSH_FAIL=ssh_fail, PUBLISH_FAIL=publish_fail)
                    success = count == 10 and ssh_fail == publish_fail == '0'
                    self.assertEqual(r.returncode == 0, success, r.stderr)
                    self.assertEqual((out / 'old').exists(), not success)
                    if success:
                        self.assertEqual(len(list(out.iterdir())), 10)
                    self.assertFalse(list(root.glob('*.new.*')))

    def test_remote_failure_stops_before_later_steps(self):
        remote = BUILD.split('"${SSH[@]}" "set -e;', 1)[1].split('\n# Validate', 1)[0]
        remote = 'set -e;' + remote.rstrip().removesuffix('"')
        remote = remote.replace('\\$P', '$P')
        with tempfile.TemporaryDirectory() as tmp:
            # Substitute directory and stub sudo; never invoke podman/compiler/SSH.
            remote = remote.replace('/tmp', tmp)
            for fail_at in (1, 2, 3):
                (Path(tmp) / 'calls').unlink(missing_ok=True)
                r = shell('CTR=fixture; n=0\n'
                          'sudo() { n=$((n+1)); echo called >>"$CALLS"; '
                          'if [[ "$n" == "$FAIL_AT" ]]; then return 7; fi; }\n' + remote,
                          tmp, CALLS=str(Path(tmp) / 'calls'), FAIL_AT=str(fail_at))
                self.assertEqual(r.returncode, 7, r.stderr)
                self.assertEqual((Path(tmp) / 'calls').read_text().splitlines(), ['called'] * fail_at)

    def test_source_account_failure_regression(self):
        source = subprocess.check_output(['git', 'show',
            'e10519f3bb5da28226b22bf49c1e42c2c50d2b05:sm8650-overlay/usr/bin/konkr-apk'],
            cwd=ROOT, text=True)
        block = source.split("    if ! asx 'dumpsys account'", 1)[1].split('\n  fi\n  echo "$GAMESCOPE', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            r = shell('SYS="$PWD"; PROPS_REV=2\n'
                      'asx() { if [[ "$1" == "dumpsys account" ]]; then return 1; '
                      'else touch cleared; fi; }\n'
                      + "    if ! asx 'dumpsys account'" + block, tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(tmp) / 'cleared').exists())
            self.assertTrue((Path(tmp) / 'props-rev').exists())

    def test_version_guard_and_ssh_option_globs(self):
        guard = next(x for x in BUILD.splitlines() if x.startswith('[[ "$ver" =~'))
        opts = BUILD.split('SSH_OPTS=(-i', 1)[1].split('\nSSH=(ssh', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            for ver in ('v3.0.3', '3.0.3', '', '../other', 'v3/../../other', 'v3\nv4'):
                r = shell(guard, tmp, ver=ver)
                self.assertEqual(r.returncode == 0, ver in ('v3.0.3', '3.0.3'))
            (Path(tmp) / 'identity-one').touch()
            r = shell('SSH_OPTS=(-i' + opts + '\nprintf "%s\\n" "${SSH_OPTS[@]}"', tmp,
                      KONKR_SSH_OPTS='-o IdentityFile=identity-* -p 2222')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.splitlines()[-4:], ['-o', 'IdentityFile=identity-*', '-p', '2222'])


if __name__ == '__main__':
    unittest.main()
