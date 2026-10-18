#!/usr/bin/env python3
"""Non-compiling patch regression for queue 084.

DWC3_SOURCE_ROOT must contain linux-{7.1.2,7.2,7.2.8}/drivers/usb/dwc3/
dwc3-qcom.c from the corresponding gregkh/linux tags. No download, build,
device operation or repository mutation is performed. Only temporary copies
are patched. ROCKNIX's separate patch inventory is reviewed in report 084.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
PATCH_ROOT = Path(os.environ.get('DWC3_PATCH_ROOT', REPO))
TARGET = 'drivers/usb/dwc3/dwc3-qcom.c'
BASE_SHA256 = 'cf8257168ad0e8e201a003e7d2e3344cdfa08b33eb6ae6451728bc497d2ce008'
TABLET = 'external-and-mods/kernel-tb321fu/patches/0012-usb-typec-the-tb321fu-type-c-ports.patch'
PARENT = '59768208ed2781209ff730af65e24de5e66a0843'


def dwc3_section(data):
    text = data.decode('latin1')
    start = text.index('--- a/' + TARGET + '\n')
    end = text.find('\ndiff --git ', start)
    return text[start:] if end == -1 else text[start:end] + '\n'


def function(text, name):
    match = re.search(r'^static [^\n]+\b' + name + r'\([^;]*?\n\{', text, re.M)
    if not match:
        raise AssertionError('Missing function: ' + name)
    return text[match.start():text.index('\n}', match.end()) + 2]


class Dwc3PatchRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'DWC3_SOURCE_ROOT' not in os.environ:
            raise RuntimeError('Set DWC3_SOURCE_ROOT to the inspected pinned source directory')
        cls.sources = Path(os.environ['DWC3_SOURCE_ROOT'])
        cls.patches = {
            soc: next((PATCH_ROOT / ('external-and-mods/kernel-' + soc) / 'patches')
                      .glob('*apply-a-role-change-from-sleep-after-resume.patch')).read_bytes()
            for soc in ('sm8250', 'sm8550', 'sm8650', 'sm8750')
        }
        cls.old_tablet = subprocess.check_output(['git', 'show', PARENT + ':' + TABLET], cwd=REPO)

    def apply(self, version, patches):
        base = (self.sources / ('linux-' + version) / TARGET).read_bytes()
        self.assertEqual(hashlib.sha256(base).hexdigest(), BASE_SHA256)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / TARGET
            path.parent.mkdir(parents=True)
            path.write_bytes(base)
            for data in patches:
                result = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0'], cwd=temp,
                                        input=dwc3_section(data), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return path.read_text()

    def test_all_shared_copies_agree(self):
        self.assertEqual(len(set(self.patches.values())), 1)

    def test_selected_kernel_versions_apply_without_fuzz(self):
        for soc, version in [('sm8250', '7.2.8'), ('sm8550', '7.1.2'),
                             ('sm8550', '7.2.8'), ('sm8650', '7.2.8'), ('sm8750', '7.2')]:
            with self.subTest(soc=soc, version=version):
                self.apply(version, [self.patches[soc]])

    def test_inherited_tablet_chain_applies_without_fuzz(self):
        self.apply('7.2.8', [self.patches['sm8650'], (PATCH_ROOT / TABLET).read_bytes()])

    def test_tablet_hardware_sequences_unchanged(self):
        before = self.apply('7.2.8', [self.old_tablet])
        after = self.apply('7.2.8', [self.patches['sm8650'], (PATCH_ROOT / TABLET).read_bytes()])
        for name in ('dwc3_qcom_host_ss_powerup_quirk', 'dwc3_qcom_reinit_usb2_phys'):
            self.assertEqual(function(before, name), function(after, name))
        # All added tablet C lines survive; this includes quirk predicates,
        # PHY error recovery, property names, debug messages and probe hooks.
        def additions(data):
            return [line[1:] for line in dwc3_section(data).splitlines()
                    if line.startswith('+') and not line.startswith('+++') and line[1:].strip()]
        self.assertEqual(additions(self.old_tablet), additions((PATCH_ROOT / TABLET).read_bytes()))

    def test_other_tablet_drivers_preserved_byte_for_byte(self):
        marker = b'diff --git a/' + TARGET.encode()
        def without_dwc3(data):
            start = data.index(marker)
            end = data.index(b'\ndiff --git ', start + 1)
            return data[:start] + data[end:]
        self.assertEqual(without_dwc3(self.old_tablet), without_dwc3((PATCH_ROOT / TABLET).read_bytes()))


if __name__ == '__main__':
    unittest.main()
