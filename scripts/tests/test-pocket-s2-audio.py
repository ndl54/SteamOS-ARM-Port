#!/usr/bin/env python3
"""Source and isolated shell regressions; no ALSA/PipeWire/device operations."""
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
UCM = ROOT / 'sm8650-overlay/usr/share/alsa/ucm2'
PROFILE = UCM / 'Qualcomm/sm8650/APS2/SM8650-APS2.conf'
HIFI = PROFILE.with_name('HiFi.conf')
SETUP = ROOT / 'sm8650-overlay/usr/lib/steamos/sm8550-audio-setup'


def speaker_setup(compatible, ucm_ok=True):
    # Run only the actual successful-UCM mixer block with fixture sysfs and
    # an amixer shell function. Never execute the helper's host chmod/service paths.
    text = SETUP.read_text()
    begin = text.index('  if ucm SM8650-APS2')
    end = text.index('\n  exit 0\nfi', begin)
    block = text[begin:end]
    with tempfile.TemporaryDirectory(prefix='s2-audio-test-') as d:
        base = Path(d)
        compat = base / 'compatible'
        if compatible is not None:
            compat.write_bytes(compatible)
        calls = base / 'calls'
        calls.touch()
        block = block.replace('/sys/firmware/devicetree/base/compatible', shlex.quote(str(compat)))
        block = block.replace('/tmp/sm8550-alsaucm.log', shlex.quote(str(base / 'ucm-log')))
        program = ('card_id=3\nlog() { :; }\n'
                   f'ucm() {{ return {0 if ucm_ok else 1}; }}\n'
                   f'amixer() {{ printf "%s\\n" "$*" >> {shlex.quote(str(calls))}; }}\n' + block)
        subprocess.run(['bash', '-c', program], check=True, capture_output=True)
        return calls.read_text().splitlines()


class PocketS2Audio(unittest.TestCase):
    def test_s2_skips_forced_digital_maximum(self):
        calls = speaker_setup(b'ayaneo,pocket-s2\0qcom,sm8650\0')
        self.assertEqual(len(calls), 1)
        self.assertIn("Speakers Volume 17,17", calls[0])

    def test_compatible_token_not_substring(self):
        for value in (b'ayaneo,pocket-s20\0', b'ayaneo,pocket-s2-pro\0',
                      b'prefix-ayaneo,pocket-s2\0', b'AYANEO,pocket-s2\0', b''):
            with self.subTest(value=value):
                calls = speaker_setup(value)
                self.assertEqual(sum('Digital Volume 100%' in c for c in calls), 2)

    def test_other_boards_retain_previous_setup(self):
        for value in (b'konkr,pocket-fit\0qcom,sm8650\0',
                      b'ayaneo,pocketevo\0qcom,sm8550\0', b'lenovo,tb321fu\0'):
            with self.subTest(value=value):
                calls = speaker_setup(value)
                self.assertEqual(len(calls), 3)
                self.assertIn('WSA_RX0 Digital Volume 100%', calls[1])
                self.assertIn('WSA_RX1 Digital Volume 100%', calls[2])

    def test_missing_identity_keeps_previous_setup(self):
        self.assertEqual(len(speaker_setup(None)), 3)

    def test_ucm_failure_only_uses_existing_route_fallback(self):
        calls = speaker_setup(b'ayaneo,pocket-s2\0', False)
        self.assertEqual(len(calls), 3)
        self.assertFalse(any('Volume' in c for c in calls))
        self.assertTrue(all('Audio Mixer' in c for c in calls))

    def test_card_entrypoint_reaches_digital_remap(self):
        entry = UCM / 'conf.d/sm8650/SM8650-APS2.conf'
        self.assertEqual(entry.resolve(), PROFILE.resolve())
        self.assertIn("name='Speakers Digital Playback Volume'", entry.read_text())
        self.assertIn("name='WSA_RX0 Digital Volume'\".vindex.0 0", entry.read_text())
        self.assertIn("name='WSA_RX1 Digital Volume'\".vindex.1 0", entry.read_text())

    def test_ucm_gates_match_pinned_first_compatible_only(self):
        for path in (PROFILE, HIFI):
            text = path.read_text()
            self.assertIn('String "${sys:firmware/devicetree/base/compatible}"', text)
            regex = re.search(r'Regex "([^"]+)"', text).group(1)
            self.assertTrue(re.search(regex, 'ayaneo,pocket-s2'))
            for other in ('ayaneo,pocketevo', 'konkr,pocket-fit', 'ayaneo,pocket-s20',
                          'ayaneo,pocket-s2-pro', 'lenovo,tb321fu', ''):
                self.assertIsNone(re.search(regex, other))


if __name__ == '__main__':
    unittest.main()
