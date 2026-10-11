#!/usr/bin/env python3
"""Board isolation regression checks; no hardware, kernel build or root access."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
BASE = '4673fa6'


def baseline(path):
    return subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=REPO)


class Isolation(unittest.TestCase):
    def test_shared_kernel_and_audio_files_match_before_pocket_evo_work(self):
        paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE,
            'external-and-mods/kernel-sm8550', 'external-and-mods/kernel-sm8650',
            'external-and-mods/kernel-sm8750',
            'sm8550-overlay/usr/share/alsa/ucm2',
            'sm8650-overlay/usr/lib/konkr/konkr-sleep',
            'steamos-overlay/usr/lib/steamos-arm/steamos-arm-wifi-wake',
            'external-and-mods/kernel-common/steamos.config'], cwd=REPO, text=True).splitlines()
        for path in paths:
            if path.endswith('/ayaneo-AYANEOPocketEVO-.conf'):
                continue
            with self.subTest(path=path):
                self.assertEqual((REPO / path).read_bytes(), baseline(path))

    def recipe(self, device, override=''):
        return subprocess.run(['bash', '-c',
            'source "$1"; printf "%s\\n" "$KNAME" "$DTBS" "$PORT_DIRS" "$PATCH_SKIP"',
            'recipe', str(REPO / f'external-and-mods/kernel-{device}/soc.env')],
            env={**os.environ, 'DTBS_OVERRIDE': override}, capture_output=True, text=True)

    def test_device_kernel_limits_dtb_and_replaces_only_its_patch_set(self):
        result = self.recipe('pocketevo')
        self.assertEqual(result.returncode, 0, result.stderr)
        name, dtbs, ports, skip = result.stdout.splitlines()
        self.assertEqual((name, dtbs, ports), ('pocketevo', 'qcs8550-ayaneo-pocketevo',
                                              'kernel-sm8550 kernel-pocketevo'))
        patches = list((REPO / 'external-and-mods/kernel-pocketevo/patches').glob('*.patch'))
        replacements = [p for p in patches if ('0' + p.name[1:]) in skip.split()]
        self.assertEqual(len(replacements), 6)
        for patch in patches:
            self.assertNotIn(patch.name, skip.split())
        for patch in replacements:
            self.assertIn('0' + patch.name[1:], skip.split())
        # New feature patches and exact-context replacements remain EVO-only.
        for device in ('sm8550', 'sm8650', 'sm8750', 'pocketevo'):
            check = subprocess.run(['bash', '-c',
                'source "$1"; printf "%s\n%s" "${PATCH_FUZZ:-2}" "${PATCH_OVERRIDE_DIR:-}"',
                'recipe', str(REPO / f'external-and-mods/kernel-{device}/soc.env')],
                capture_output=True, text=True, check=True)
            fuzz, override = check.stdout.split('\n', 1)
            self.assertEqual(fuzz, '0' if device == 'pocketevo' else '2')
            self.assertEqual(bool(override), device == 'pocketevo')
        self.assertNotEqual(self.recipe('pocketevo', 'qcs8550-ayn-odin2').returncode, 0)
        self.assertNotEqual(self.recipe('pocketevo', 'qcs8550-ayaneo-pocketevo qcs8550-ayn-odin2').returncode, 0)
        self.assertEqual(self.recipe('pocketevo', dtbs).returncode, 0)

    def test_build_fixes_require_the_device_recipe(self):
        source = (REPO / 'external-and-mods/kernel-common/build.sh').read_text()
        prefix = source[:source.index('WORK="${WORK:')]
        start = prefix.index('HERE=')
        end = prefix.index('\n', start)
        prefix = prefix[:start] + 'HERE="' + str(REPO / 'external-and-mods/kernel-common') + '"' + prefix[end:]
        probe = '\nprintf "DTBS=%s\\n" "$DTBS"; bash -c \'printf "EXPORTED=%s\\n" "${LOCALVERSION-unset}"\''
        for device in ('sm8550', 'sm8650', 'sm8750', 'pocketevo'):
            result = subprocess.run(['bash', '-c', prefix + probe, 'build', device],
                                    env={**os.environ, 'LOCALVERSION': '-test'},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('EXPORTED=' + ('unset' if device == 'pocketevo' else '-test'), result.stdout)
        start = source.index("  local static_pattern=")
        end = source.index('  file "$bb"', start)
        fragment = source[start:end].replace('local static_pattern', 'static_pattern')
        for device in ('sm8550', 'sm8650', 'sm8750', 'pocketevo'):
            result = subprocess.check_output(['bash', '-c', fragment + '\nprintf "%s" "$static_pattern"'],
                                             env={**os.environ, 'SOC_ARG': device}, text=True)
            self.assertEqual(result, 'statically linked|static-pie linked' if device == 'pocketevo' else 'statically linked')

    def test_ucm_new_profile_is_referenced_only_by_evo(self):
        root = REPO / 'sm8550-overlay/usr/share/alsa/ucm2'
        refs = [p.name for p in root.rglob('*.conf') if '/AYANEO/PocketEVO/HiFi.conf' in p.read_text()]
        self.assertEqual(refs, ['ayaneo-AYANEOPocketEVO-.conf'])

    def test_portal_generator_leaves_other_boards_untouched(self):
        source = (REPO / 'sm8550-overlay/usr/lib/systemd/user-generators/pocket-evo-portal').read_text()
        for board in ('ayaneo,pocketevo', 'ayaneo,pocketevo-other', 'ayn,odin2',
                      'ayaneo,pocketds', 'konkr,pocketfit', ''):
            with self.subTest(board=board), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                dt = root / 'compatible'
                dt.write_bytes(board.encode() + b'\0qcom,sm8550\0')
                out = root / 'generator'
                out.mkdir()
                result = subprocess.run(['sh', '-c', source.replace('/proc/device-tree/compatible', str(dt)),
                                         'generator', str(out)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                dropin = out / 'plasma-xdg-desktop-portal-kde.service.d/99-odin-wayland.conf'
                if board == 'ayaneo,pocketevo':
                    self.assertEqual(os.readlink(dropin), '/dev/null')
                else:
                    self.assertEqual(list(out.iterdir()), [])

    def test_non_evo_audio_behavior_matches_baseline(self):
        spec = importlib.util.spec_from_file_location('session_tests', REPO / 'scripts/tests/test-pocket-evo-session.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        current = module.AUDIO
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / 'audio'
            original.write_bytes(baseline('steamos-overlay/usr/lib/steamos/sm8550-audio-pipewire'))
            for model in ('AYN Odin 2', 'AYANEO Pocket DS', 'KONKR Pocket FIT', 'AYANEO Pocket S2', 'AYANEO Pocket EVO Other'):
                for dp in (False, True):
                    outputs = []
                    for path in (original, current):
                        module.AUDIO = path
                        case = module.SessionPolicies()
                        case.setUp()
                        try:
                            outputs.append(case.audio(model, dp))
                        finally:
                            case.doCleanups()
                    with self.subTest(model=model, dp=dp):
                        self.assertEqual(*outputs)
        module.AUDIO = current

    def test_extra_debug_collection_is_inert_on_other_boards(self):
        source = (REPO / 'external-and-mods/kernel-common/initramfs/bootdebug').read_text()
        function = source[source.index('runtime_evidence() {'):source.index('# The boot before')]
        result = subprocess.run(['sh', '-c', 'pocket_evo=0\n' + function + '\nruntime_evidence'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))


if __name__ == '__main__':
    unittest.main()
