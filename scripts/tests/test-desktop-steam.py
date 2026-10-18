#!/usr/bin/env python3
"""No-display regressions for desktop-steam's shared-DPI side effect.

The absolute Steam exec is replaced only in a temporary script. xrdb and
xrandr are fake commands; no X server, Steam, installer or build is invoked.
DESKTOP_STEAM_SOURCE can point at the upstream script to reproduce failures.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get(
    "DESKTOP_STEAM_SOURCE", REPO / "steamos-overlay/usr/lib/steamos/desktop-steam"))


class DesktopSteamTests(unittest.TestCase):
    def run_launcher(self, width, dpi, args, status=0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake"
            fake.write_text("#!/usr/bin/env python3\n" + '''
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps([name, sys.argv[1:]]) + '\\n')
if name == 'xrandr':
    print('Screen 0: minimum 16 x 16, current ' + os.environ['WIDTH'] + ' x 1080, maximum 32767 x 32767')
elif name == 'xrdb':
    if sys.argv[1:] == ['-query']:
        print('Xft.dpi: ' + os.environ['DPI'])
    else:
        Path(os.environ['MUTATION']).write_text(sys.stdin.read())
elif name == 'steam':
    sys.exit(int(os.environ['STEAM_STATUS']))
''')
            fake.chmod(0o755)
            for name in ("xrdb", "xrandr", "steam"):
                (root / name).symlink_to(fake)
            source = SOURCE.read_text()
            self.assertEqual(source.count('exec /usr/bin/steam "$@"'), 1)
            wrapper = root / "desktop-steam"
            wrapper.write_text(source.replace('exec /usr/bin/steam "$@"', 'exec steam "$@"'))
            env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}",
                       CALLS=str(root / "calls"), MUTATION=str(root / "mutation"),
                       WIDTH=str(width), DPI=str(dpi), STEAM_STATUS=str(status))
            result = subprocess.run(["bash", str(wrapper), *args], env=env,
                                    capture_output=True, text=True, timeout=5)
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
            self.assertFalse((root / "mutation").exists(), "launcher overwrote shared X resources")
            self.assertEqual(calls, [["steam", args]], "launcher queried/mutated the desktop")
            self.assertEqual(result.returncode, status)
            self.assertEqual(result.stderr, "")

    def test_narrow_panel_keeps_explicit_dpi(self):
        self.run_launcher(1240, 120, ["-silent", "%U"])

    def test_multi_output_and_fractional_scale(self):
        self.run_launcher(3160, "144.5", ["-forcedesktopscaling", "1.5"])

    def test_rotation_does_not_change_session_dpi(self):
        self.run_launcher(720, 144, ["steam://open/keyboard"])

    def test_exact_argv_and_exit_status(self):
        self.run_launcher(1920, 120, ["", "two words", "*", "$(no-command)", "--"], 23)


if __name__ == "__main__":
    unittest.main()
