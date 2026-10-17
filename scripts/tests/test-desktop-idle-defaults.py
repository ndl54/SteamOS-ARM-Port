#!/usr/bin/env python3
"""Run only the idle-config shell fragment with mocked KDE commands in temp dirs."""
import configparser
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / 'steamos-overlay/usr/lib/steamos/sm8550-prepare-plasma'
FRAGMENT = PREPARE.read_text().split('# Seed missing idle-display settings once.', 1)[1]
FRAGMENT = '# Seed missing idle-display settings once.' + FRAGMENT
KEY = 'TurnOffDisplayWhenIdle'
PROFILES = ('AC', 'Battery', 'LowBattery')
MOCK = r'''
import configparser, json, os, pathlib, re, sys
args = sys.argv[1:]
profile = args[args.index('--group') + 1]
section = profile + '][Display'
key = args[args.index('--key') + 1]
root = pathlib.Path(os.environ.get('XDG_CONFIG_HOME') or (os.environ['HOME'] + '/.config'))
path = root / 'powerdevilrc'
read = pathlib.Path(sys.argv[0]).name == 'kreadconfig6'
with (root / 'calls').open('a') as out:
    out.write(json.dumps(['read' if read else 'write', profile]) + '\n')
if os.environ.get('FAIL_READ' if read else 'FAIL_WRITE') == profile:
    sys.exit(2)
def config(p):
    c = configparser.ConfigParser(interpolation=None)
    c.optionxform = str
    c.SECTCRE = re.compile(r"\[(?P<header>.+)\]")
    c.read(p)
    return c
c = config(path)
if read:
    fallback = args[args.index('--default') + 1] if '--default' in args else ''
    defaults = config(root / 'system-defaults')
    print(c.get(section, key, fallback=defaults.get(section, key, fallback=fallback)))
else:
    if os.environ.get('SILENT_WRITE') == profile:
        sys.exit(0)
    if not c.has_section(section):
        c.add_section(section)
    c.set(section, key, args[-1])
    with path.open('w') as out:
        c.write(out)
'''


class IdleDefaults(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conf = self.root / 'separate-config'
        self.conf.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('kreadconfig6', 'kwriteconfig6'):
            tool = self.bin / name
            tool.write_text('#!' + sys.executable + '\n' + MOCK)
            tool.chmod(0o755)
        # Only the isolated fragment can run; no session, service or device code.
        self.env = dict(os.environ, HOME=str(self.root / 'home'),
                        XDG_CONFIG_HOME=str(self.conf),
                        PATH=str(self.bin) + ':/usr/bin:/bin')
        self.path = self.conf / 'powerdevilrc'
        self.mark = self.conf / 'steamos-arm/display-off-idle-v1'

    def run_fragment(self, fragment=FRAGMENT, **extra):
        result = subprocess.run(['/bin/bash', '-u', '-c', fragment],
                                env=dict(self.env, **extra), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def values(self):
        c = configparser.ConfigParser(interpolation=None)
        c.SECTCRE = re.compile(r"\[(?P<header>.+)\]")
        c.read(self.path)
        return [c.get(p + '][Display', KEY, fallback=None) for p in PROFILES]

    def calls(self):
        path = self.conf / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_absent_config_seed_and_repeat(self):
        self.run_fragment()
        self.assertEqual(self.values(), ['false'] * 3)
        self.assertTrue(self.mark.exists())
        before = self.path.read_bytes(), self.calls()
        self.run_fragment()
        self.assertEqual(before, (self.path.read_bytes(), self.calls()))
        self.assertFalse((self.root / 'home/.config').exists())

    def test_explicit_values_and_unrelated_settings_preserved(self):
        for value in ('true', 'false', '', 'unrecognized', '__steamos_arm_missing__'):
            with self.subTest(value=value):
                self.mark.unlink(missing_ok=True)
                text = '# Custom brightness and timeout\n' + ''.join(
                    f'[{p}][Display]\n{KEY}={value}\nDisplayBrightness=42\n'
                    'DimDisplayWhenIdle=false\nTurnOffDisplayIdleTimeoutSec=999\n'
                    for p in PROFILES)
                self.path.write_text(text)
                self.run_fragment()
                self.assertEqual(self.path.read_text(), text)

    def test_inherited_defaults_need_no_user_file(self):
        (self.conf / 'system-defaults').write_bytes(
            (ROOT / 'steamos-overlay/etc/xdg/powerdevilrc').read_bytes())
        self.run_fragment()
        self.assertTrue(self.mark.exists())
        self.assertFalse(self.path.exists())
        self.assertFalse(any(c[0] == 'write' for c in self.calls()))

    def test_mixed_profile_and_post_marker_customization(self):
        self.path.write_text(f'[AC][Display]\n{KEY}=true\n')
        self.run_fragment()
        self.assertEqual(self.values(), ['true', 'false', 'false'])
        self.path.write_text(f'[Battery][Display]\n{KEY}=true\n')
        before = self.path.read_bytes(), self.calls()
        self.run_fragment()
        self.assertEqual(before, (self.path.read_bytes(), self.calls()))

    def test_failures_retry_without_overwriting_completed_profiles(self):
        for failure in ('FAIL_READ', 'FAIL_WRITE', 'SILENT_WRITE'):
            with self.subTest(failure=failure):
                self.path.unlink(missing_ok=True)
                self.mark.unlink(missing_ok=True)
                result = self.run_fragment(**{failure: 'Battery'})
                self.assertIn('will retry', result.stderr)
                self.assertFalse(self.mark.exists())
                self.assertEqual(self.values()[0], 'false')
                # A user edit between retries is preserved.
                self.path.write_text(self.path.read_text().replace('false', 'true'))
                self.run_fragment()
                self.assertEqual(self.values(), ['true', 'false', 'false'])
                self.assertTrue(self.mark.exists())

    def test_missing_reader_or_writer_does_not_mark(self):
        # PATH contains only our mocks, so absent KDE tools cannot fall through
        # to an installed desktop command on another test host.
        self.env['PATH'] = str(self.bin)
        for name in ('kreadconfig6', 'kwriteconfig6'):
            tool = self.bin / name
            renamed = tool.with_suffix('.hidden')
            tool.rename(renamed)
            self.run_fragment()
            self.assertFalse(self.mark.exists())
            self.assertFalse(self.path.exists())
            renamed.rename(tool)

    def test_marker_failure_does_not_block_desktop(self):
        (self.conf / 'steamos-arm').write_text('existing file')
        result = self.run_fragment()
        self.assertIn('could not mark', result.stderr)
        self.assertEqual(self.values(), ['false'] * 3)
        self.assertEqual((self.conf / 'steamos-arm').read_text(), 'existing file')

    def test_home_fallback(self):
        home_config = self.root / 'home/.config'
        home_config.mkdir(parents=True)
        self.run_fragment(XDG_CONFIG_HOME='')
        self.assertTrue((home_config / 'steamos-arm/display-off-idle-v1').exists())
        self.assertFalse(self.path.exists())

    def test_upstream_regressions_reproduced(self):
        upstream = subprocess.check_output([
            'git', 'show', '6d997f54848e41a1ba415fab2d389f8e5fe1cf29:' +
            str(PREPARE.relative_to(ROOT))], cwd=ROOT, text=True)
        fragment = 'mark=' + upstream.split('\nmark=', 1)[1]
        self.path.write_text(f'[AC][Display]\n{KEY}=true\n')
        self.run_fragment(fragment)
        self.assertEqual(self.values(), ['false'] * 3)  # overwrote user true
        self.mark.unlink()
        self.path.unlink()
        self.run_fragment(fragment, FAIL_WRITE='Battery')
        self.assertTrue(self.mark.exists())  # upstream marks despite failure
        self.assertIsNone(self.values()[1])

    def test_staging_preserves_existing_home_and_seeds_missing(self):
        script = (ROOT / 'scripts/install-system-fixes.sh').read_text()
        start = script.index('if [[ -f "$OVL/etc/xdg/powerdevilrc" ]]; then',
                             script.index('install -m 0644 "$OVL/etc/xdg/kscreenlockerrc"'))
        block = script[start:script.index('\n# Official Plasma', start)]
        stage = self.root / 'stage'
        home = stage / 'home/steamos'
        (home / '.config').mkdir(parents=True)
        (stage / 'etc/skel/.config').mkdir(parents=True)
        target = home / '.config/powerdevilrc'
        for kind in ('file', 'symlink', 'absent'):
            with self.subTest(kind=kind):
                target.unlink(missing_ok=True)
                if kind == 'file':
                    target.write_text('custom bytes\n')
                elif kind == 'symlink':
                    target.symlink_to('missing-custom-config')
                self.run_fragment(block, OVL=str(ROOT / 'steamos-overlay'),
                                  R=str(stage), HOME_DST=str(home))
                if kind == 'file':
                    self.assertEqual(target.read_text(), 'custom bytes\n')
                elif kind == 'symlink':
                    self.assertTrue(target.is_symlink())
                    self.assertFalse(target.exists())
                else:
                    self.assertEqual(target.read_bytes(),
                                     (ROOT / 'steamos-overlay/etc/xdg/powerdevilrc').read_bytes())


if __name__ == '__main__':
    unittest.main()
