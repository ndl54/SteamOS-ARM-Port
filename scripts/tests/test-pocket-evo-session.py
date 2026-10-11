#!/usr/bin/env python3
"""Run session policies with fake audio/network commands and temporary sysfs.

No device, user state or SD-card writes. Run: python3 scripts/tests/test-pocket-evo-session.py
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
AUDIO = REPO / 'steamos-overlay/usr/lib/steamos/sm8550-audio-pipewire'
WIFI = REPO / 'sm8550-overlay/usr/lib/pocketevo/pocket-evo-wifi-wake'
SLEEP = REPO / 'sm8550-overlay/usr/lib/pocketevo/pocket-evo-sleep'
SHARED_SLEEP = REPO / 'sm8650-overlay/usr/lib/konkr/konkr-sleep'


def fake_tool():
    tool = Path(sys.argv[2]).name
    args = sys.argv[3:]
    root = Path(os.environ['EVO_TEST_ROOT'])
    with (root / 'calls').open('a') as out:
        out.write(json.dumps([tool, *args]) + '\n')
    if tool == 'timeout':
        return subprocess.call(args[1:])
    if tool in ('amixer', 'audio-setup', 'iw', 'sleep'):
        return 0
    if tool == 'nmcli':
        if 'GENERAL.STATE' in args:
            print('100 (connected)')
        elif args[-2:] == ['radio', 'wifi']:
            print('enabled')
        return 0
    if tool != 'pactl':
        return 0
    profile_file = root / 'profile'
    profile = profile_file.read_text() if profile_file.exists() else 'off'
    if args == ['list', 'short', 'cards']:
        print('0\talsa_card.platform-sound\tmodule-alsa-card.c')
    elif args == ['list', 'cards']:
        print('Card #0\n\tName: alsa_card.platform-sound\n\tProfiles:')
        print('\t\tHiFi (Speaker): Speaker (available: yes)')
        print('\t\tHiFi (DisplayPort, Speaker): DP (available: yes)')
        print('\tActive Profile: ' + profile)
    elif args[0] == 'set-card-profile':
        profile_file.write_text(args[2])
    elif args == ['list', 'short', 'sinks']:
        # Force the first probe to miss a sink, reproducing async creation.
        count_file = root / 'sink-probes'
        count = int(count_file.read_text()) if count_file.exists() else 0
        count_file.write_text(str(count + 1))
        if count == 0:
            return 0
        suffix = 'pro-output-0' if profile == 'pro-audio' else (
            'HiFi__DisplayPort__sink' if 'DisplayPort' in profile else 'HiFi__Speaker__sink')
        print(f'56\talsa_output.platform-sound.{suffix}\tPipeWire\ts16le\tRUNNING')
    elif args[0] == 'set-default-sink':
        (root / 'default').write_text(args[1])
    elif args == ['get-default-sink'] and (root / 'default').exists():
        print((root / 'default').read_text())
    return 0


class SessionPolicies(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='evo-policy-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        command = f'exec {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} --fake-tool "$0" "$@"\n'
        for name in ['pactl', 'amixer', 'audio-setup', 'timeout', 'iw', 'nmcli', 'sleep']:
            p = self.bin / name
            p.write_text('#!/bin/sh\n' + command)
            p.chmod(0o755)
        self.env = dict(os.environ, EVO_TEST_ROOT=str(self.root),
                        EVO_TEST_BIN=str(self.bin),
                        XDG_STATE_HOME=str(self.root / 'state'),
                        PATH=str(self.bin) + ':' + os.environ['PATH'])

    def calls(self):
        p = self.root / 'calls'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def audio(self, model, dp=False):
        model_path = self.root / 'model'
        model_path.write_bytes(model.encode() + b'\0')
        drm = self.root / 'drm'
        (drm / 'card0-DP-1').mkdir(parents=True)
        (drm / 'card0-DP-1/status').write_text('connected' if dp else 'disconnected')
        source = AUDIO.read_text().split('\nif ! wait_card; then', 1)[0]
        source = source.replace('export PATH="/usr/sbin:/usr/bin:/sbin:/bin${PATH:+:$PATH}"',
                                'export PATH="$EVO_TEST_BIN:$PATH"')
        source = source.replace('/sys/firmware/devicetree/base/model', str(model_path))
        source = source.replace('/sys/class/drm/', str(drm) + '/')
        source = source.replace('/usr/lib/steamos/sm8550-audio-setup', 'audio-setup')
        result = subprocess.run(['bash', '-c', source + '\napply_policy\n'],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.calls()

    def test_evo_uses_ucm_and_waits_for_speaker(self):
        calls = self.audio('AYANEO Pocket EVO')
        self.assertEqual((self.root / 'profile').read_text(), 'HiFi (Speaker)')
        self.assertTrue((self.root / 'default').read_text().endswith('HiFi__Speaker__sink'))
        self.assertFalse(any(c[0] in ('amixer', 'audio-setup') for c in calls))
        self.assertIn(['sleep', '0.25'], calls)
        self.assertFalse(any(c[:2] == ['pactl', 'set-sink-volume'] for c in calls))

    def test_evo_displayport_uses_ucm_without_odin_mixers(self):
        calls = self.audio('AYANEO Pocket EVO', dp=True)
        self.assertTrue((self.root / 'profile').read_text().startswith('HiFi (DisplayPort'))
        self.assertTrue((self.root / 'default').read_text().endswith('HiFi__DisplayPort__sink'))
        self.assertFalse(any(c[0] in ('amixer', 'audio-setup') for c in calls))

    def test_odin_retains_pro_audio_policy(self):
        calls = self.audio('AYN Odin 2')
        self.assertEqual((self.root / 'profile').read_text(), 'pro-audio')
        self.assertTrue((self.root / 'default').read_text().endswith('pro-output-0'))
        self.assertTrue(any(c[0] == 'audio-setup' for c in calls))

    def test_sm8650_retains_ucm_policy(self):
        self.audio('KONKR Pocket FIT')
        self.assertEqual((self.root / 'profile').read_text(), 'HiFi (Speaker)')

    def test_wifi_watch_scans_known_channel_without_radio_reset(self):
        mark = self.root / 'wifi-mark'
        mark.touch()
        last = self.root / 'wifi-last'
        last.write_text('5180\nTest network\n')
        source = WIFI.read_text().replace('/run/pocketevo/wifi-was-connected', str(mark))
        source = source.replace('/run/konkr/wifi-last', str(last))
        result = subprocess.run(['bash', '-c', source, 'wifi-wake', 'watch'],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(mark.exists())
        calls = self.calls()
        self.assertIn(['iw', 'dev', 'wlan0', 'scan', 'trigger', 'freq', '5180', 'ssid', 'Test network'], calls)
        self.assertIn(['timeout', '3', 'nmcli', '-w', '2', '-t', '-g', 'GENERAL.STATE', 'device', 'show', 'wlan0'], calls)
        self.assertFalse(any('off' in c for c in calls))

    def test_post_restores_wifi_before_scan_without_mutating_sysfs(self):
        # Use real post/step control flow with mock hardware functions. Both
        # the full SM8550 path and the existing light path must start a watch.
        source = SLEEP.read_text().split('\n# Other boards retain', 1)[0].split('\ncase "${1:-}" in', 1)[0]
        source = source.replace('/sys/module/', str(self.root / 'modules') + '/')
        for is_light in (0, 1):
            mock = '''
report_end() { :; }
sleep_debug() { :; }
ufs_on() { echo ufs; }
light() { return LIGHT_RESULT; }
touch_on() { echo touch; }
modprobe() { echo reload; }
timeout() { shift; "$@"; }
wifi_watch_start() { echo scan; }
audio() { echo audio; }
systemctl() { :; }
post
'''.replace('LIGHT_RESULT', str(is_light))
            result = subprocess.run(['bash', '-c', source + '\n' + mock],
                                    env=self.env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            events = result.stdout.splitlines()
            self.assertIn('scan', events)
            self.assertLess(events.index('ufs'), events.index('scan'))
            if is_light == 1:  # shell exit 1 => full preparation
                self.assertLess(events.index('reload'), events.index('scan'))

    def ufs_fixture(self, compatible, helper=SLEEP):
        dt = self.root / 'compatible'
        dt.write_bytes(b'\0'.join(c.encode() for c in compatible) + b'\0')
        driver = self.root / 'ufshcd-qcom'
        host = driver / '1d84000.ufshc'
        host.mkdir(parents=True)
        for path in (driver / 'bind', driver / 'unbind', host / 'clkscale_enable'):
            path.write_text('untouched\n')
        state = self.root / 'ufs-unbound'
        source = helper.read_text().split('\n# Other boards retain', 1)[0].split('\ncase "${1:-}" in', 1)[0]
        source = source.replace('/run/konkr/ufs-unbound', str(state))
        source = source.replace('/proc/device-tree/compatible', str(dt))
        source = source.replace('/sys/bus/platform/drivers/ufshcd-qcom', str(driver))
        source = source.replace('/run/pocketevo/ufs-unbound', str(state))
        source = source.replace('/sys/module/', str(self.root / 'modules') + '/')
        return source, driver, state

    def test_evo_pre_post_leave_ufs_bound_and_restore_other_devices(self):
        source, driver, state = self.ufs_fixture(
            ['ayaneo,pocketevo', 'qcom,qcs8550', 'qcom,sm8550'])
        # Exercise the full pre/post path. UFS use detection must not even
        # run: the board policy applies to both SD and internal installs.
        mock = '''
report_start() { :; }
report_end() { :; }
sleep_debug() { :; }
sync() { :; }
wifi_mark() { :; }
wake_sources() { :; }
touch_off() { echo 0; }
touch_on() { echo touch-restored; }
audio() { echo audio-$1; }
modprobe() { echo wifi-restored; }
timeout() { shift; "$@"; }
wifi_watch_start() { echo scan; }
systemctl() { :; }
ufs_in_use() { echo unexpected-ufs-probe >&2; return 1; }
pre
post
'''
        result = subprocess.run(['bash', '-c', source + '\n' + mock],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(state.exists())
        for path in (driver / 'bind', driver / 'unbind',
                     driver / '1d84000.ufshc/clkscale_enable'):
            self.assertEqual(path.read_text(), 'untouched\n')
        self.assertNotIn('unexpected-ufs-probe', result.stderr)
        self.assertIn('stage=ufs_off end rc=0', result.stderr)
        self.assertIn('stage=ufs_on end rc=0', result.stderr)
        events = result.stdout.splitlines()
        self.assertIn('touch-restored', events)
        self.assertIn('audio-0', events)
        self.assertLess(events.index('wifi-restored'), events.index('scan'))

    def test_sleep_dispatch_selects_only_exact_evo_and_preserves_arguments(self):
        fallback = self.bin / 'original-sleep'
        fallback.write_text('#!/bin/bash\nprintf "original:%s\\n" "$@"\nexit 17\n')
        fallback.chmod(0o755)
        dt = self.root / 'dispatch-compatible'
        source = SLEEP.read_text().replace('/proc/device-tree/compatible', str(dt))
        source = source.replace('/usr/lib/konkr/konkr-sleep', str(fallback))
        # Exercise the actual dispatch with inert pre/post implementations.
        source = source.replace('  pre) pre ;;', '  pre) echo evo-pre ;;')
        source = source.replace('  post) post ;;', '  post) echo evo-post ;;')
        for compatible in (['ayaneo,pocketevo', 'qcom,sm8550'],
                           ['ayn,odin2', 'qcom,sm8550'],
                           ['konkr,pocketfit', 'qcom,sm8650'],
                           ['ayaneo,pocketevo-other', 'qcom,sm8550'], []):
            dt.write_bytes(b'\0'.join(c.encode() for c in compatible) + b'\0')
            for mode in ('pre', 'post'):
                with self.subTest(compatible=compatible, mode=mode):
                    result = subprocess.run(['bash', '-c', source, 'sleep', mode, 'extra arg'],
                                            capture_output=True, text=True, timeout=5)
                    evo = 'ayaneo,pocketevo' in compatible
                    self.assertEqual(result.returncode, 0 if evo else 17, result.stderr)
                    self.assertEqual(result.stdout, f'evo-{mode}\n' if evo else
                                     f'original:{mode}\noriginal:extra arg\n')

    def test_sleep_installer_keeps_shared_helpers_and_installs_dropin(self):
        root = self.root / 'rootfs'
        for path in ('usr/lib/konkr/konkr-sleep',
                     'usr/lib/steamos-arm/steamos-arm-wifi-wake'):
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('original-helper')
        subprocess.run(['bash', str(REPO / 'scripts/install-pocket-evo-sleep.sh'), str(root)],
                       check=True, capture_output=True)
        for helper in ('pocket-evo-sleep', 'pocket-evo-wifi-wake'):
            path = Path('usr/lib/pocketevo') / helper
            self.assertEqual((root / path).read_bytes(), (REPO / 'sm8550-overlay' / path).read_bytes())
            self.assertTrue(os.access(root / path, os.X_OK))
        for path in ('usr/lib/konkr/konkr-sleep',
                     'usr/lib/steamos-arm/steamos-arm-wifi-wake'):
            self.assertEqual((root / path).read_text(), 'original-helper')
        dropin = root / 'usr/lib/systemd/system/konkr-sleep.service.d/50-pocket-evo.conf'
        self.assertIn('ExecStart=\nExecStart=/usr/lib/pocketevo/pocket-evo-sleep pre', dropin.read_text())
        self.assertIn('ExecStop=\nExecStop=/usr/lib/pocketevo/pocket-evo-sleep post', dropin.read_text())

    def test_other_boards_keep_ufs_detach_and_rebind(self):
        # Same GPU/SoC is insufficient to opt a different board out; the
        # Pocket FIT workaround also remains intact on SM8650.
        for compatible in (['ayn,odin2', 'qcom,sm8550'],
                           ['konkr,pocketfit', 'qcom,sm8650']):
            with self.subTest(compatible=compatible), tempfile.TemporaryDirectory() as d:
                saved_root, self.root = self.root, Path(d)
                try:
                    source, driver, state = self.ufs_fixture(compatible, SHARED_SLEEP)
                    result = subprocess.run(
                        ['bash', '-c', source + '\nufs_in_use() { return 1; }; ufs_off; ufs_on'],
                        env=self.env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((driver / 'unbind').read_text(), '1d84000.ufshc\n')
                    self.assertEqual((driver / 'bind').read_text(), '1d84000.ufshc\n')
                    self.assertEqual((driver / '1d84000.ufshc/clkscale_enable').read_text(), '0\n')
                    self.assertFalse(state.exists())
                finally:
                    self.root = saved_root


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fake-tool':
        raise SystemExit(fake_tool())
    unittest.main()
