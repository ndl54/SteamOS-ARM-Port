#!/usr/bin/env python3
"""Source045 integration regressions: isolated shell blocks and temp files only.

Never launches an installer, build, service, audio tool or accesses device sysfs.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'dafefe9c8e02caccd003d83fa0c9a02366dfdde7'
OVERLAY = ROOT / 'sm8250-overlay'
APPLY = 'scripts/apply-overlays.sh'
AUDIO = 'steamos-overlay/usr/lib/steamos/sm8550-audio-pipewire'
SETUP = 'sm8650-overlay/usr/lib/steamos/sm8550-audio-setup'


def source(path):
    return subprocess.check_output(['git', 'show', f'{SOURCE}:{path}'], cwd=ROOT, text=True)


def shell(code, **env):
    result = subprocess.run(['bash', '-c', code], text=True, capture_output=True,
                            env={**os.environ, **env})
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout


def unclosed_csets(text):
    return [n for n, line in enumerate(text.splitlines(), 1)
            if line.lstrip().startswith('cset "') and not re.fullmatch(r'\s*cset "[^"\n]*"\s*', line)]


class Integration(unittest.TestCase):
    def stage(self, text, root, soc):
        # Supply the actual overlay manifest instead of Bash 4's mapfile so
        # this policy test also runs on macOS Bash 3. Only the copy/remove
        # block is executed; install is a fixture-only portable implementation.
        block = text.split('mapfile -t _s8250_files ', 1)[1].split('\n', 1)[1]
        block = block.split('# Log collector behind', 1)[0]
        files = sorted(str(p.relative_to(OVERLAY)) for tree in ('etc', 'usr')
                       for p in (OVERLAY / tree).rglob('*') if p.is_file())
        script = '''set -euo pipefail
log() { :; }
install() { shift 2; mkdir -p "$(dirname "$2")"; cp "$1" "$2"; chmod 0644 "$2"; }
_s8250_files=(''' + ' '.join(map(shlex.quote, files)) + ')\n' + block
        shell(script, R=str(root), S8250_OVL=str(OVERLAY), SOC=soc)
        return files

    def test_persistent_profiles_reproduces_source_and_repairs(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td); upper = r/'var/lib/overlays/etc/upper'
            upper.mkdir(parents=True)
            rel = 'inputplumber/devices.d/02-retroid-pocket-865.yaml'
            stale = upper/rel; stale.parent.mkdir(parents=True); stale.write_text('stale')
            self.stage(source(APPLY), r, 'sm8250')
            self.assertEqual(stale.read_text(), 'stale')  # source misses active upper
            self.stage((ROOT/APPLY).read_text(), r, 'sm8250')
            self.assertEqual(stale.read_bytes(), (OVERLAY/'etc'/rel).read_bytes())
            stale.write_text('stale again')
            self.stage((ROOT/APPLY).read_text(), r, 'sm8250')
            self.assertEqual(stale.read_bytes(), (OVERLAY/'etc'/rel).read_bytes())

    def test_soc_switch_removes_only_owned_files_in_both_layers(self):
        for soc in ('sm8550', 'sm8650', 'sm8750'):
            with self.subTest(soc=soc), tempfile.TemporaryDirectory() as td:
                r = Path(td); upper = r/'var/lib/overlays/etc/upper'; upper.mkdir(parents=True)
                keep = [r/'etc/inputplumber/devices.d/custom.yaml', upper/'inputplumber/devices.d/custom.yaml',
                        r/'usr/share/alsa/ucm2/conf.d/sm8250/REDMAGIC 6.conf']
                for p in keep:
                    p.parent.mkdir(parents=True, exist_ok=True); p.write_text('preserve')
                files = self.stage((ROOT/APPLY).read_text(), r, 'sm8250')
                self.stage(source(APPLY), r, soc)
                self.assertTrue((upper/'inputplumber/devices.d/02-ayn-thor-lite.yaml').exists())
                self.stage((ROOT/APPLY).read_text(), r, soc)
                self.stage((ROOT/APPLY).read_text(), r, soc)
                for f in files:
                    self.assertFalse((r/f).exists(), f)
                    if f.startswith('etc/'):
                        self.assertFalse((upper/f[4:]).exists(), f)
                self.assertTrue(all(p.read_text() == 'preserve' for p in keep))

    def test_fresh_root_stages_all_files_without_creating_upper(self):
        with tempfile.TemporaryDirectory() as td:
            r = Path(td)
            files = self.stage((ROOT/APPLY).read_text(), r, 'sm8250')
            for f in files:
                self.assertEqual((r/f).read_bytes(), (OVERLAY/f).read_bytes())
                self.assertEqual((r/f).stat().st_mode & 0o777, 0o644)
            self.assertFalse((r/'var/lib/overlays/etc/upper').exists())

    def test_ucm_commands_and_duplicate_entrypoints(self):
        old_bad = 0
        ucm = OVERLAY/'usr/share/alsa/ucm2'
        for p in ucm.rglob('*.conf'):
            old_bad += len(unclosed_csets(source(str(p.relative_to(ROOT)))))
            self.assertEqual(unclosed_csets(p.read_text()), [], str(p))
        self.assertEqual(old_bad, 150)  # malformed original cset commands
        canonical = [p for p in ucm.rglob('*.conf') if 'conf.d' not in p.parts]
        for alias in (ucm/'conf.d/sm8250').glob('*.conf'):
            self.assertTrue(any(alias.read_bytes() == p.read_bytes() for p in canonical), str(alias))
        # Device-local includes resolve; generic ALSA codec/lib includes are
        # supplied by the target rootfs, outside this lexical/source check.
        for p in ucm.rglob('*.conf'):
            for rel in re.findall(r'\bFile\s+"(/[^"\n]+)"', p.read_text()):
                if not rel.startswith(('/lib/', '/codecs/')):
                    self.assertTrue((ucm/rel.lstrip('/')).is_file(), (p, rel))

    def audio(self, text, model, compat, dp=False):
        start = text.index('POCKET_EVO=0\n')
        end = text.index('\nMODE=once', start)
        config = text[start:end]
        # Replace only hard-coded read paths with fake DT files. No host path
        # is read, no daemon is started; policy effects are recorded stubs.
        config = config.replace('/sys/firmware/devicetree/base/model', '"$MODEL_FILE"')
        config = config.replace('/sys/firmware/devicetree/base/compatible', '"$COMPAT_FILE"')
        policy = text.split('apply_policy() {\n', 1)[1].split('\nif ! wait_card;', 1)[0]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); (p/'model').write_bytes(model.encode()+b'\0'); (p/'compatible').write_bytes(compat)
            script = config + '''
log() { :; }
card_name() { echo alsa_card.platform-sound; }
drm_dp() { [[ "$DP" == 1 ]]; }
local_profile() { echo 'HiFi (Headphones, Speaker)'; }
dp_profile() { echo HDMI; }
set_profile() { echo "profile=$2"; }
enable_dp_mixers() { echo ODIN_DP; }
restore_speaker_mixers() { echo ODIN_SPEAKER; }
wait_sink() { :; }
find_sink() { echo fixture_sink; }
set_default() { :; }
persist() { :; }
pactl_ok() { :; }
apply_policy() {
''' + policy + '\napply_policy\n'
            return shell(script, MODEL_FILE=str(p/'model'), COMPAT_FILE=str(p/'compatible'), DP=str(int(dp)))

    def test_sm8250_uses_ucm_preserving_other_boards(self):
        old = subprocess.check_output(['git', 'show',
            '9e4e5b1de750be1ebd581048d4e9784f1a7838ef:'+AUDIO], cwd=ROOT, text=True)
        new = (ROOT/AUDIO).read_text()
        for model in ('Retroid Pocket 5', 'AYN Thor Lite', 'MANGMI Air Y Pro', 'MANGMI Pocket Max', 'AYANEO Pocket MICRO 2'):
            compat = b'vendor,board\0qcom,sm8250\0'
            self.assertIn('ODIN_SPEAKER', self.audio(old, model, compat))
            for dp in (False, True):
                out = self.audio(new, model, compat, dp)
                self.assertNotIn('ODIN_', out)
                self.assertIn('profile=HDMI' if dp else 'profile=HiFi (Headphones, Speaker)', out)
        for model, compat in [('AYANEO Pocket EVO', b'ayaneo,pocketevo\0qcom,sm8550\0'),
                              ('AYN Odin 2', b'ayn,odin2\0qcom,sm8550\0'),
                              ('KONKR Pocket FIT', b'ayaneo,pocket-fit\0qcom,sm8650\0'),
                              ('unknown', b'qcom,sm82500\0'), ('unknown', b'')]:
            for dp in (False, True):
                self.assertEqual(self.audio(new, model, compat, dp), self.audio(old, model, compat, dp))

    def refresh(self, text, model):
        block = text.split('REFRESH_HZ="${GAMESCOPE_REFRESH:-}"', 1)[1]
        block = 'REFRESH_HZ="${GAMESCOPE_REFRESH:-}"'+block.split('# Dual-screen handhelds:', 1)[0]
        block = block.replace('/usr/lib/steamos/panel-modes --max "$OUTPUT"', 'printf 120')
        block = block.replace('/usr/lib/steamos/panel-modes --rates "$OUTPUT"', 'printf 60,90,120')
        block = block.replace('/sys/firmware/devicetree/base/model', '"$MODEL_FILE"')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'model'; p.write_bytes(model.encode()+b'\0')
            return shell(block+'\nprintf "%s|%s|%s" "$REFRESH_HZ" "$PANEL_RATES" "$STEAM_DISPLAY_REFRESH_LIMITS"',
                         MODEL_FILE=str(p), GAMESCOPE_REFRESH='120', STEAM_DISPLAY_REFRESH_LIMITS='60,120')

    def test_sixty_hz_policy_and_other_panel_preservation(self):
        path = 'steamos-overlay/usr/lib/steamos/gamescope-session'
        old = source(path); new = (ROOT/path).read_text()
        for model in ('Retroid Pocket 5', 'Retroid Pocket Flip2'):
            self.assertEqual(self.refresh(old, model), '120|60|60,120')
            self.assertEqual(self.refresh(new, model), '60|60|60')
        for model in ('Retroid Pocket 5 Visionox', 'Retroid Pocket Flip2 Visionox',
                      'AYANEO Pocket EVO', 'AYN Thor Lite', 'Retroid Pocket 50', ''):
            self.assertEqual(self.refresh(new, model), self.refresh(old, model))

    def test_sm8250_setup_skips_legacy_wait(self):
        text = (ROOT/SETUP).read_text()
        block = text.split('# SM8250 profiles are applied', 1)[1].split('wait_card() {', 1)[0]
        block = '# SM8250 profiles are applied'+block
        block = block.replace('/sys/firmware/devicetree/base/compatible', '"$COMPAT_FILE"')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'compatible'
            for compat, expect in [(b'board\0qcom,sm8250\0', False), (b'qcom,sm82500\0', True),
                                   (b'ayaneo,pocketevo\0qcom,sm8550\0', True), (b'', True)]:
                p.write_bytes(compat)
                out = shell('log() { :; }\n'+block+'echo LEGACY_WAIT\n', COMPAT_FILE=str(p))
                self.assertEqual('LEGACY_WAIT' in out, expect)


if __name__ == '__main__':
    unittest.main()
