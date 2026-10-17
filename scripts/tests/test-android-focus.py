#!/usr/bin/env python3
"""Extracted patcher/launch functions, text fixtures and mocks; no Android/build."""
import ast
import os
from pathlib import Path
import re
import select
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
APK = (ROOT / 'sm8650-overlay/usr/bin/konkr-apk').read_text()
SOURCE = '4dc525e6504dfe5e8510217923ca51089ea06f26'


def patcher(apk):
    return apk.split("<<'EOF'\n", 1)[1].split('\nEOF', 1)[0]


def function(name):
    return name + '() {' + APK.split(name + '() {', 1)[1].split('\n}\n', 1)[0] + '\n}\n'


def fixture(root, brand=True):
    (root / 'liblepton').mkdir(exist_ok=True)
    files = {}
    for node in ast.parse(patcher(APK)).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and getattr(node.value.func, 'id', '') == 'patch':
            name, old, _ = [ast.literal_eval(a) for a in node.value.args]
            if old not in files.get(name, ''):
                files[name] = files.get(name, '') + old
    files['liblepton/mounting.sh'] += '    podman_cmdline --pid=private --ipc=private --uts=private\n'
    files['liblepton/mounting.sh'] += '    for OVERLAY in "${LEPTON_OVERLAY}" "${GUESTOS_OVERLAY}"; do\n'
    files['liblepton/properties.sh'] = ('    props_echo "ro.product.brand=Steam Frame"\n' if brand else '') + '    props_echo "ro.product.model=Lepton"\n    props_echo "ro.product.manufacturer=Valve"\n'
    for name, data in files.items():
        (root / name).write_text(data)
    return files['liblepton/properties.sh']


def apply(root, apk=APK):
    return subprocess.run(['python3', '-B', '-', str(root)], input=patcher(apk), text=True, capture_output=True, check=True)


def shell(code, root, **env):
    return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + code], cwd=root, env={**os.environ, **env}, text=True, capture_output=True, timeout=5)


MOCKS = r'''
RUNDIR="$PWD"; APPS="$PWD"; iterations=0
# Portable real advisory locking on an ordinary temp file; no systemd/cgroup.
flock() { python3 -c 'import fcntl,sys
try: fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError: sys.exit(1)'; }
die() { echo "$*" >&2; exit 1; }
ensure_android() { echo ensure >>trace; }
steam_launch_appid() { printf '%s' "${APPID-123}"; }
set_window_appid() { echo "id:$1" >>trace; }
schedule_idle_stop() { echo idle >>trace; }
cmd_install() { echo unexpected-install >>trace; exit 98; }
android_up() { iterations=$((iterations + 1)); ((iterations < 6)); }
systemctl() { echo "service:$*" >>trace; }
asx() {
  echo "$1" >>trace
  case "$1" in
    'pm path '*) echo package:/fixture.apk ;;
    'cmd package resolve-activity '*) if [[ "$MODE" == noactivity ]]; then echo missing; else echo com.test/.Main; fi ;;
    'am start '*)
      case "$MODE" in
        failed) return 7 ;;
        error) echo 'Error: Activity not started' ;;
        exception) echo 'java.lang.SecurityException: denied' ;;
        *) echo 'Starting: Intent { fixture }' ;;
      esac ;;
    'pidof '*) return 1 ;;
    'dumpsys window '*) echo 'mCurrentFocus=launcher3' ;;
  esac
}
sleep() {
  if [[ "$MODE" == signal ]]; then kill -TERM "$$";
  elif [[ "$MODE" == hold ]]; then echo READY; read -r ignored;
  elif [[ "$MODE" == looperror ]]; then return 8;
  fi
}
'''


class AndroidFocus(unittest.TestCase):
    def test_patch_repeat_upgrade_and_property_fallback(self):
        before = subprocess.check_output(['git', 'show', '5bd1808d2c1d69a5e2e780cde5615706dcf89c48:sm8650-overlay/usr/bin/konkr-apk'], cwd=ROOT, text=True)
        for brand in (True, False):
            for upgrade in (True, False):
                with self.subTest(brand=brand, upgrade=upgrade), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    original_props = fixture(root, brand)
                    if upgrade:
                        apply(root, before)
                    first = apply(root)
                    mount = (root / 'liblepton/mounting.sh').read_text()
                    props = (root / 'liblepton/properties.sh').read_text()
                    for _ in range(3):
                        self.assertEqual(apply(root).stderr, '')
                        self.assertEqual((root / 'liblepton/mounting.sh').read_text(), mount)
                        self.assertEqual((root / 'liblepton/properties.sh').read_text(), props)
                    self.assertEqual(first.stderr, '')
                    self.assertEqual(mount.count('podman_cmdline --cgroups=disabled'), 1)
                    self.assertEqual(mount.count('podman_cmdline --ulimit stack=-1:-1'), 1)
                    self.assertEqual(props.count('# konkr-apk: certified identity'), 1)
                    blocks = re.findall(r'    # konkr-apk: (?:low mmap[^\n]*|container stays[^\n]*)\n    if .*?\n    fi\n', mount, re.S)
                    self.assertEqual(len(blocks), 2)
                    for overlay in ('', '/overlay'):
                        r = shell('podman_cmdline() { echo "$*"; }\n' + ''.join(blocks), tmp, KONKR_LEPTON_OVERLAY=overlay)
                        self.assertEqual(r.returncode, 0, r.stderr)
                        self.assertEqual(sorted(r.stdout.splitlines()), sorted(['--cgroups=disabled', '--ulimit stack=-1:-1']) if overlay else [])
                        r = shell('props_echo() { echo "$*"; }\n' + props, tmp, KONKR_LEPTON_OVERLAY=overlay)
                        expected = ['ro.product.brand=google', 'ro.product.model=Pixel 5', 'ro.product.manufacturer=Google'] if overlay else [x.split('"')[1] for x in original_props.splitlines()]
                        self.assertEqual(r.returncode, 0, r.stderr)
                        self.assertEqual(r.stdout.splitlines(), expected)

    def test_assigned_source_reproduces_repeat_and_nested_identity(self):
        source = subprocess.check_output(['git', 'show', SOURCE + ':sm8650-overlay/usr/bin/konkr-apk'], cwd=ROOT, text=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            apply(root, source)
            self.assertEqual((root / 'liblepton/properties.sh').read_text().count('# konkr-apk: certified identity'), 2)
            apply(root, source)
            mount = (root / 'liblepton/mounting.sh').read_text()
            self.assertEqual(mount.count('podman_cmdline --cgroups=split'), 2)
            self.assertEqual(mount.count('podman_cmdline --ulimit stack=-1:-1'), 2)

    def test_unknown_property_identity_warns_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root)
            p = root / 'liblepton/properties.sh'; p.write_text('# future identity\n')
            r = apply(root)
            self.assertIn('product identity changed upstream', r.stderr)
            self.assertEqual(p.read_text(), '# future identity\n')

    def test_launch_exit_failure_signal_and_no_steam_id(self):
        for mode in ('normal', 'failed', 'error', 'exception', 'signal', 'looperror', 'noactivity'):
            for appid in ('123', ''):
                with self.subTest(mode=mode, appid=appid), tempfile.TemporaryDirectory() as tmp:
                    r = shell(MOCKS + function('cmd_run') + 'cmd_run com.test', tmp, MODE=mode, APPID=appid)
                    lines = (Path(tmp) / 'trace').read_text().splitlines()
                    self.assertEqual(r.returncode == 0, mode in ('normal', 'signal'), r.stderr)
                    ids = [x for x in lines if x.startswith('id:')]
                    self.assertEqual(ids, ['id:0'] if mode == 'noactivity' else ['id:' + (appid or '0'), 'id:0'])
                    self.assertEqual(lines[-1], 'idle')
                    if mode == 'signal': self.assertIn('am force-stop com.test', lines)
                    if mode in ('failed', 'error', 'exception'): self.assertNotIn('pidof com.test', lines)

    def test_second_title_and_idle_timer_cannot_take_active_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = 'set -euo pipefail\n' + MOCKS + function('cmd_run') + 'cmd_run com.test'
            p = subprocess.Popen(['bash', '-c', code], cwd=tmp, env={**os.environ, 'MODE': 'hold'}, text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertTrue(select.select([p.stdout], [], [], 3)[0], 'first title did not reach wait')
                self.assertEqual(p.stdout.readline().strip(), 'READY')
                prior = (Path(tmp) / 'trace').read_text()
                r = shell(MOCKS + function('cmd_run') + 'cmd_run com.other', tmp, MODE='normal')
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('Another Android title', r.stderr)
                self.assertEqual((Path(tmp) / 'trace').read_text(), prior)
                r = shell(MOCKS + function('cmd_idle_stop') + 'cmd_idle_stop', tmp, MODE='normal')
                self.assertEqual(r.returncode, 0)
                self.assertEqual((Path(tmp) / 'trace').read_text(), prior)
                p.terminate(); p.communicate(timeout=3)
                self.assertEqual(p.returncode, 0)
                r = shell(MOCKS + function('cmd_idle_stop') + 'cmd_idle_stop', tmp, MODE='normal')
                self.assertEqual(r.returncode, 0)
                self.assertIn('service:--user stop konkr-android.service', (Path(tmp) / 'trace').read_text())
            finally:
                if p.poll() is None: p.kill(); p.communicate()

    def test_no_display_does_not_call_xprop(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = shell('xprop() { echo unexpected; return 99; }\n' + function('set_window_appid') + 'set_window_appid 123', tmp, DISPLAY='')
            self.assertEqual((r.returncode, r.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main()
