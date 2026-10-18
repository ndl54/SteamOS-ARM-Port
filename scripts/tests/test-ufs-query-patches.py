#!/usr/bin/env python3
"""Queue 088: replay selected UFS patches on temporary pinned source copies.

Set UFS_SOURCE_ROOT to directories 7.1.2, 7.2, 7.2.8 and elden containing
only drivers/ufs/core/ufshcd.c and include/ufs/ufs.h. Sources are hash-checked.
No network, compiler, build/source-preparation entrypoint or device access.
ROCKNIX overlap inventory is recorded separately in report 088.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
PATCH_ROOT = Path(os.environ.get('UFS_PATCH_ROOT', REPO))
TARGETS = ('drivers/ufs/core/ufshcd.c', 'include/ufs/ufs.h')
HASHES = {
    '7.1.2': ('fb45d3acba59c187c27adf1462636760e96e105f54216a9bea2cc38365a0a075',
              'dccdf83317c491bb7c6d818c42d094d5104124173e755aee1666dbdde4a80f30'),
    '7.2': ('2f610a861ecd220dc6a3bc7744c031adcb71b77c3a8d66e7d4d43bcbcc6c7e47',
            '5fc96ca66cadd33f8cd45de3171061cfe75fad5e41fa65fa24e8b88e3868b3f4'),
    '7.2.8': ('be6ed1fe9891b273e62ea867a4c5a4ea720f627ed66c6f396dd8519e309c4bdc',
              '5fc96ca66cadd33f8cd45de3171061cfe75fad5e41fa65fa24e8b88e3868b3f4'),
}
HASHES['elden'] = HASHES['7.2.8']
VARIANTS = [('sm8250', {}), ('sm8550', {'SM8550_RECIPE': '7.1'}),
            ('sm8550', {'SM8550_RECIPE': '7.2'}), ('sm8650', {}),
            ('sm8650', {'SM8650_RECIPE': '7.1'}), ('sm8750', {}),
            ('pocketevo', {}), ('tb321fu', {}), ('elden', {})]


def recipe(soc, extra):
    env = dict(os.environ)
    for key in ('SM8550_RECIPE', 'SM8650_RECIPE', 'DTBS_OVERRIDE'):
        env.pop(key, None)
    env.update(extra)
    path = PATCH_ROOT / f'external-and-mods/kernel-{soc}/soc.env'
    # Read declarative recipe data only, never source the build script.
    version, skips, ports, override = subprocess.check_output(
        ['bash', '-c', 'source "$1"; printf "%s\\n" "$KVER" "${PATCH_SKIP:-}" '
         '"${PORT_DIRS:-kernel-' + soc + '}" "${PATCH_OVERRIDE_DIR:-}"',
         'bash', str(path)], env=env, text=True).splitlines()
    selected = []
    for port in ports.split():
        for patch in sorted((PATCH_ROOT / 'external-and-mods' / port / 'patches').glob('*.patch')):
            if patch.name in skips.split():
                continue
            alternative = Path(override) / patch.name
            if override and alternative.is_file():
                patch = alternative
            data = patch.read_bytes()
            if any(('+++ b/' + target + '\n').encode() in data for target in TARGETS):
                selected.append(data)
    return 'elden' if soc == 'elden' else version, selected


class UfsQueryPatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'UFS_SOURCE_ROOT' not in os.environ:
            raise RuntimeError('Set UFS_SOURCE_ROOT to the inspected pinned source directory')
        cls.sources = Path(os.environ['UFS_SOURCE_ROOT'])
        evo = PATCH_ROOT / 'external-and-mods/kernel-pocketevo/patches'
        cls.original_pair = [next(evo.glob(prefix + '*.patch')).read_bytes()
                             for prefix in ('9067-', '9068-')]

    def apply(self, version, patches):
        with tempfile.TemporaryDirectory() as temp:
            for target, digest in zip(TARGETS, HASHES[version]):
                data = (self.sources / version / target).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
                path = Path(temp) / target
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            for data in patches:
                result = subprocess.run(['patch', '-p1', '-N', '--batch', '--fuzz=0'],
                                        cwd=temp, input=data, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout.decode() + result.stderr.decode())
            return tuple((Path(temp) / target).read_bytes() for target in TARGETS)

    def test_each_recipe_selects_one_complete_pair_or_legacy_none(self):
        for soc, env in VARIANTS:
            with self.subTest(soc=soc, env=env):
                version, patches = recipe(soc, env)
                self.assertEqual(patches, [] if version == '7.1.2' else self.original_pair)

    def test_actual_recipe_replays_without_fuzz_or_duplicates(self):
        for soc, env in VARIANTS:
            with self.subTest(soc=soc, env=env):
                version, patches = recipe(soc, env)
                output = self.apply(version, patches)
                # A pair adds precisely one capability field and rejection branch.
                expected = 0 if version == '7.1.2' else 1
                self.assertEqual(output[1].count(b'bool timestamp_sup;'), expected)
                self.assertEqual(output[0].count(b'else if (response == QUERY_RESULT_INVALID_IDN)'), expected)

    def test_evo_result_matches_existing_fork_pair(self):
        version, selected = recipe('pocketevo', {})
        self.assertEqual(self.apply(version, selected), self.apply(version, self.original_pair))


if __name__ == '__main__':
    unittest.main()
