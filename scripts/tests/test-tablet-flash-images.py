#!/usr/bin/env python3
"""Exercise cleanup failures without root, mounts, images or compilation."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / 'scripts/mk-tablet-flash-images.sh').read_text()
CLEANUP = SCRIPT[SCRIPT.index('cleanup() {'):SCRIPT.index('trap cleanup EXIT')]


class Cleanup(unittest.TestCase):
    def run_cleanup(self, status=0, busy='', detach_failure=''):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'calls'
            # Every destructive command is a shell function; no mount or loop
            # device is touched. Exercise the actual function as an EXIT trap.
            shell = r'''
set -euo pipefail
W=/mock/work FAT=/mock/fat LOOP=/mock/source
mountpoint() { return 0; }
umount() {
  printf 'umount %s\n' "$1" >> "$CALLS"
  [[ "$1" != "$BUSY" ]]
}
losetup() {
  printf 'detach %s\n' "$2" >> "$CALLS"
  [[ "$2" != "$DETACH_FAILURE" ]]
}
rm() { printf 'rm %s\n' "$*" >> "$CALLS"; }
'''
            shell += CLEANUP + '\ntrap cleanup EXIT\nexit "$INITIAL_STATUS"\n'
            result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True,
                env={**os.environ, 'CALLS': str(log), 'BUSY': busy,
                     'DETACH_FAILURE': detach_failure, 'INITIAL_STATUS': str(status)})
            return result, log.read_text().splitlines()

    def test_success_and_original_failure_status(self):
        for status in (0, 7):
            with self.subTest(status=status):
                result, calls = self.run_cleanup(status)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(calls, [f'umount /mock/work/{m}'
                    for m in ('super', 'ud', 'home', 'root', 'boot')] +
                    ['detach /mock/fat', 'detach /mock/source', 'rm -rf /mock/work'])
                self.assertEqual(result.stderr, '')

    def test_busy_mount_preserves_directory_and_loop_devices(self):
        for mount in ('super', 'ud', 'home', 'root', 'boot'):
            for status in (0, 7):
                with self.subTest(mount=mount, status=status):
                    result, calls = self.run_cleanup(status, busy=f'/mock/work/{mount}')
                    self.assertEqual(result.returncode, status or 1)
                    self.assertEqual(len(calls), 5)
                    self.assertTrue(all(c.startswith('umount ') for c in calls))
                    self.assertIn('preserved /mock/work', result.stderr)

    def test_failed_detach_preserves_directory(self):
        for device in ('/mock/fat', '/mock/source'):
            with self.subTest(device=device):
                result, calls = self.run_cleanup(detach_failure=device)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(any(c.startswith('rm ') for c in calls))
                self.assertIn('preserved /mock/work', result.stderr)


class BootConfiguration(unittest.TestCase):
    def test_bootlabel_default_override_and_root_precedence(self):
        source = (REPO / 'external-and-mods/kernel-common/initramfs/init').read_text()
        parser = source[source.index('extra=0'):source.index('# USB gadget:')]
        for cmdline, expected in (
            ('root=PARTLABEL=STORAGE', 'ROCKNIX PARTLABEL=STORAGE'),
            ('root=PARTLABEL=userdata steamos.bootlabel=super', 'super PARTLABEL=userdata'),
            ('root=PARTUUID=sd-image', 'ROCKNIX PARTUUID=sd-image'),
            ('steamos.root=PARTLABEL=userdata root=android steamos.bootlabel=super',
             'super PARTLABEL=userdata'),
        ):
            with self.subTest(cmdline=cmdline):
                shell = 'cat() { printf "%s" "$CMDLINE"; };\n' + parser
                shell += '\nprintf "%s %s" "$bootlabel" "$rootarg"'
                result = subprocess.run(['sh', '-c', shell], capture_output=True, text=True,
                    env={**os.environ, 'CMDLINE': cmdline}, check=True)
                self.assertEqual(result.stdout, expected)

    def test_current_panel_menu_rewrite(self):
        # Render only the existing menu text template; never execute image or
        # boot staging scripts, download assets, or run a kernel build.
        stage = (REPO / 'scripts/stage-tb321fu-boot.sh').read_text()
        template = stage.split('    cat <<CFG\n', 1)[1].split('\nCFG', 1)[0]
        result = subprocess.run(['bash', '-c', '''
source external-and-mods/kernel-tb321fu/soc.env
source external-and-mods/kernel-common/cmdline.sh
source external-and-mods/tb321fu-boot/release.env
build_cmdline PARTLABEL=STORAGE
printf '\\n%s' "$TB321FU_DISABLE_RESERVED"
'''], cwd=REPO, capture_output=True, text=True, check=True)
        cmdline, reserved = result.stdout.split('\n', 1)
        menu = ''
        for panel in ('boe', 'csot'):
            entry = template
            for key, value in {'name': f'SteamOS ARM Port ({panel.upper()} panel)',
                               'MARK': 'test-marker', 'p': panel, 'CMDLINE': cmdline,
                               'reserved': 'qcomfdtmem disable-reserved ' + ' '.join(reserved.split())}.items():
                entry = entry.replace('$' + key, value)
            menu += entry + '\n'
        sed = re.search(r'sed -i (.*?) "\$f"', SCRIPT, re.S).group(1)
        awk = re.search(r"awk '\n(.*?)\n\s*' \"\$S/", SCRIPT, re.S).group(1)
        rewritten = subprocess.run(['bash', '-c', 'sed ' + sed], input=menu,
                                   capture_output=True, text=True, check=True).stdout
        output = subprocess.run(['awk', awk], input=rewritten,
                                capture_output=True, text=True, check=True).stdout
        entries = re.findall(r'menuentry "([^"]+)" \{(.*?)\n}', output, re.S)
        self.assertEqual(len(entries), 4)
        self.assertEqual(sum('boot text)' in title for title, _ in entries), 2)
        for title, body in entries:
            self.assertIn('root=PARTLABEL=userdata steamos.bootlabel=super', body)
            self.assertNotIn('steamos.usbimage', body)
            if 'boot text)' in title:
                for quiet in (' quiet', 'efifb:off', 'drm_client_lib.active=none',
                              '/reserved-memory/splash-region', 'loglevel=0'):
                    self.assertNotIn(quiet, body)
                self.assertIn('loglevel=7 console=tty0 systemd.show_status=1 rw rootwait', body)
            else:
                self.assertIn(' quiet', body)
                self.assertIn('/reserved-memory/splash-region', body)


if __name__ == '__main__':
    unittest.main()
