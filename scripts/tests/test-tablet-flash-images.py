#!/usr/bin/env python3
"""Exercise cleanup and boot configs without root, mounts, images or compilation."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / 'scripts/mk-tablet-flash-images.sh').read_text()
INIT = (REPO / 'external-and-mods/kernel-common/initramfs/init').read_text()
WRAPPER = (REPO / 'scripts/build-tb321fu-kernel-726.sh').read_text()
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
    def test_boot_mount_loop_fallback_and_failure_cleanup(self):
        start = INIT.index('mount_boot() {')
        function = INIT[start:INIT.index('\nif [ -n "$bootdev" ]', start)]
        for direct, free, attach, loop, expected in (
            (0, 0, 0, 0, ['mount -t vfat /mock/super /boot']),
            (1, 0, 0, 0, ['mount -t vfat /mock/super /boot', 'loop -f',
                         'loop /mock/loop /mock/super', 'mount -t vfat /mock/loop /boot',
                         'loop -d /mock/loop']),
            (1, 1, 0, 0, ['mount -t vfat /mock/super /boot', 'loop -f']),
            (1, 0, 1, 0, ['mount -t vfat /mock/super /boot', 'loop -f',
                         'loop /mock/loop /mock/super']),
            (1, 0, 0, 1, ['mount -t vfat /mock/super /boot', 'loop -f',
                         'loop /mock/loop /mock/super', 'mount -t vfat /mock/loop /boot',
                         'loop -d /mock/loop']),
        ):
            with self.subTest(direct=direct, free=free, attach=attach, loop=loop), tempfile.TemporaryDirectory() as temp:
                calls = Path(temp) / 'calls'
                shell = '''
mount() {
  echo "mount $*" >> "$CALLS"
  case "$*" in *'/mock/super'*) return "$DIRECT";; *) return "$LOOP";; esac
}
losetup() {
  echo "loop $*" >> "$CALLS"
  case "$1" in
    -f) echo /mock/loop; return "$FREE";;
    -d) return 0;;
    *) return "$ATTACH";;
  esac
}
'''
                result = subprocess.run(['sh', '-c', shell + function + '\nmount_boot\n'],
                    env={**os.environ, 'bootdev': '/mock/super', 'CALLS': str(calls),
                         'DIRECT': str(direct), 'FREE': str(free), 'ATTACH': str(attach), 'LOOP': str(loop)},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if direct == 0 else int(bool(free or attach or loop)), result.stderr)
                self.assertEqual(calls.read_text().splitlines(), expected)

    def test_userdata_mount_configuration_in_both_etc_layers(self):
        fragment = SCRIPT[SCRIPT.index("FSTAB='"):SCRIPT.index('# /home is already')]
        for device in ('tb321fu', 'elden'):
            for upper in (False, True):
                with self.subTest(device=device, upper=upper), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    layers = [root / 'etc']
                    if upper:
                        layers.append(root / 'var/lib/overlays/etc/upper')
                    for etc in layers:
                        unit = etc / 'systemd/system/home.mount'
                        unit.parent.mkdir(parents=True)
                        unit.write_text('[Mount]\nWhat=/dev/disk/by-partsets/shared/home\n')
                    # Also exercise replacing a mask without following it.
                    (layers[0] / 'systemd/system/home.mount').unlink()
                    (layers[0] / 'systemd/system/home.mount').symlink_to('/dev/null')
                    subprocess.run(['bash', '-eu', '-c', fragment], check=True,
                                   env={**os.environ, 'DEV': device, 'U': temp})
                    for etc in layers:
                        unit = etc / 'systemd/system/home.mount'
                        self.assertFalse(unit.is_symlink())
                        config = unit.read_text()
                        for line in ('What=/home', 'Where=/home', 'Type=none', 'Options=bind'):
                            self.assertIn(line, config.splitlines())
                        self.assertNotIn('by-partsets', config)
                        rows = [line.split() for line in (etc / 'fstab').read_text().splitlines()
                                if line and not line.startswith('#')]
                        self.assertEqual(rows[0][0:3], ['PARTLABEL=userdata', '/', 'ext4'])
                        self.assertFalse(any(row[1] == '/home' for row in rows))
                        boot = [row for row in rows if row[1] == '/boot']
                        self.assertEqual(len(boot), int(device == 'tb321fu'))
                        if boot:
                            self.assertEqual(boot[0][0], '/dev/disk/by-partlabel/super')
                            self.assertIn('loop', boot[0][3].split(','))
                            self.assertEqual(boot[0][-2:], ['0', '0'])
                    if not upper:
                        self.assertFalse((root / 'var/lib/overlays/etc/upper').exists())

    def test_fast_requires_prepared_tree_and_normalizes_zero(self):
        fragment = WRAPPER[WRAPPER.index('die() {'):WRAPPER.index('mkdir -p "$W/cache"')]
        for fast, prepared, valid in (('0', False, True), ('', False, True),
                                      ('1', False, False), ('1', True, True), ('bad', True, False)):
            with self.subTest(fast=fast, prepared=prepared), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                cpio = root / 'initrd.cpio'
                cpio.write_text('fixture only')
                if prepared:
                    config = root / 'cache/build/linux-7.2.6/.config'
                    config.parent.mkdir(parents=True)
                    config.write_text('CONFIG_ARM64=y\n')
                result = subprocess.run(['bash', '-eu', '-c', fragment + '\nprintf "FAST=%s" "$FAST"'],
                    env={**os.environ, 'FAST': fast, 'W': temp, 'CPIO': str(cpio)},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                if valid:
                    self.assertEqual(result.stdout, 'FAST=' + ('1' if fast == '1' else ''))

    def stage_first_config(self, esp):
        (esp / 'EFI/BOOT/grub.cfg').write_text('obsolete first-stage config\n')
        stage = (REPO / 'scripts/stage-tb321fu-boot.sh').read_text()
        fragment = stage[stage.index('mkdir -p "$ESP/boot/grub"'):
                         stage.index('# Second stage')]
        subprocess.run(['bash', '-eu', '-c', fragment], check=True,
                       env={**os.environ, 'ESP': str(esp), 'MARK': 'source-marker'})
        config = (esp / 'boot/grub/grub.cfg').read_text()
        self.assertIn('set timeout=0', config)
        self.assertIn('chainloader /EFI/BOOT/QCOMRAMP.EFI', config)
        self.assertEqual(config.count('menuentry '), 1)
        self.assertFalse((esp / 'EFI/BOOT/grub.cfg').exists())
        return config

    def test_super_only_validation_and_preserved_userdata(self):
        preflight = SCRIPT[SCRIPT.index('log() {'):SCRIPT.index('W=$(mktemp')]
        for device, mode, tool_status, valid in (
            ('tb321fu', '1', '1', True), ('elden', '1', '0', False),
            ('tb321fu', 'invalid', '0', False), ('tb321fu', '0', '1', False),
            ('elden', '0', '0', True),
        ):
            with self.subTest(device=device, mode=mode):
                # Force the root identity only inside this isolated shell;
                # command lookup must not require img2simg for super-only.
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c',
                    'id() { echo 0; }; command() { return "$TOOL_STATUS"; };\n' + preflight],
                    capture_output=True, text=True,
                    env={**os.environ, 'DEV': device, 'SUPER_ONLY': mode,
                         'TOOL_STATUS': tool_status, 'KO': '/mock/kernel'})
                self.assertEqual(result.returncode == 0, valid, result.stderr)
        setup = SCRIPT[SCRIPT.index('mkdir -p "$OUT"'):SCRIPT.index('B=$W/boot')]
        for mode in ('0', '1'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                out, work = Path(temp) / 'out', Path(temp) / 'work'
                out.mkdir()
                for name in ('userdata.img', 'userdata.simg', 'boot.img', 'super.img', 'SHA256SUMS'):
                    (out / name).write_text(name)
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c',
                    'losetup() { echo /mock/loop; }; mount() { echo "$*"; };\n' + setup],
                    capture_output=True, text=True, check=True,
                    env={**os.environ, 'OUT': str(out), 'W': str(work),
                         'IMG': '/mock/image', 'SUPER_ONLY': mode})
                self.assertEqual(len(result.stdout.splitlines()), 1 if mode == '1' else 3)
                for name in ('userdata.img', 'userdata.simg'):
                    self.assertEqual((out / name).exists(), mode == '1')
                    if mode == '1':
                        self.assertEqual((out / name).read_text(), name)
                for name in ('boot.img', 'super.img', 'SHA256SUMS'):
                    self.assertFalse((out / name).exists())

    def test_internal_installer_copies_new_config_and_rekeys_both_stages(self):
        installer = (REPO / 'external-and-mods/ufs-install/install-masios-to-internal.sh').read_text()
        start = installer.index('install_tablet_boot() {')
        function = installer[start:installer.index('\nif (( ! RESUME ));', start)]
        for panel in ('boe', 'csot'):
            with self.subTest(panel=panel), tempfile.TemporaryDirectory() as temp:
                source, work = Path(temp) / 'source', Path(temp) / 'work'
                for name in ('EFI/BOOT/BOOTAA64.EFI', 'EFI/BOOT/QCOMRAMP.EFI',
                             'Image', 'tablet/lenovo-legion-tab-gen3-boot.img',
                             'dtb/sm8650-lenovo-tb321fu-boe.dtb',
                             'dtb/sm8650-lenovo-tb321fu-csot.dtb'):
                    path = source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('fixture only\n')
                self.stage_first_config(source)
                menu = ''.join(f'''menuentry "SteamOS ARM Port ({p.upper()} panel)" {{
    search --no-floppy --file /source-marker --set=root
    devicetree /dtb/sm8650-lenovo-tb321fu-{p}.dtb
    linuxdirect /Image root=PARTLABEL=STORAGE
}}
''' for p in ('boe', 'csot'))
                (source / 'EFI/BOOT/qcomramp.cfg').write_text(menu)
                # Only the isolated function runs. Source /boot reads are
                # redirected to fixtures; flash_boot is always a shell mock.
                shell = '''
set -euo pipefail
die() { echo "$*" >&2; exit 1; }
log() { :; }
flash_boot() { printf '%s' "$1" > "$WORK/mock-flash-call"; }
'''
                # The product targets Linux sed; support BSD sed on this host.
                if os.uname().sysname == 'Darwin':
                    shell += 'sed() { if [[ $1 == -i ]]; then shift; command sed -i "" "$@"; else command sed "$@"; fi; };\n'
                shell += function.replace('/boot/', str(source) + '/').replace(
                    '$WORK' + str(source) + '/', '$WORK/boot/')
                shell += '\ninstall_tablet_boot\n'
                result = subprocess.run(['bash', '-c', shell], capture_output=True, text=True,
                    env={**os.environ, 'WORK': str(work), 'TABLET': 'tb321fu',
                         'MODEL': f'Lenovo {panel.upper()} panel'})
                self.assertEqual(result.returncode, 0, result.stderr)
                first = (work / 'boot/boot/grub/grub.cfg').read_text()
                second = (work / 'boot/EFI/BOOT/qcomramp.cfg').read_text()
                marker, = (work / 'boot').glob('steamos-arm-boot-*')
                for config in (first, second):
                    self.assertIn(f'--file /{marker.name} --set=root', config)
                    self.assertNotIn('/source-marker', config)
                self.assertEqual(second.count('menuentry '), 1)
                self.assertIn(f'/dtb/sm8650-lenovo-tb321fu-{panel}.dtb', second)
                self.assertFalse((work / 'boot/EFI/BOOT/grub.cfg').exists())
                self.assertEqual((work / 'mock-flash-call').read_text(),
                    str(source / 'tablet/lenovo-legion-tab-gen3-boot.img'))

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

    def test_one_stage_super_menu(self):
        # Render only the menu on an ordinary temporary directory. No images,
        # downloads, mounts, EFI binaries or kernel builds are executed.
        fragment = SCRIPT[SCRIPT.index('  opts="root='):SCRIPT.index('  sync; umount "$S"')]
        # macOS ships Bash 3; the product runs on Linux Bash 4+.
        if os.uname().sysname == 'Darwin':
            fragment = fragment.replace('${p^^}', '$(printf %s "$p" | tr a-z A-Z)')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'boot/grub').mkdir(parents=True)
            (root / 'EFI/BOOT').mkdir(parents=True)
            subprocess.run(['bash', '-euo', 'pipefail', '-c',
                'die() { echo "$*" >&2; exit 1; };\n' + fragment], check=True,
                env={**os.environ, 'S': temp})
            config = (root / 'boot/grub/grub.cfg').read_text()
            entries = re.findall(r'menuentry "([^"]+)" \{(.*?)\n}', config, re.S)
            boot = [(title, body) for title, body in entries if title.startswith('SteamOS')]
            self.assertEqual([title for title, _ in boot],
                ['SteamOS ARM Port (CSOT panel)', 'SteamOS ARM Port (BOE panel)'])
            for panel, (_, body) in zip(('csot', 'boe'), boot):
                self.assertIn(f'devicetree /dtb/sm8650-lenovo-tb321fu-{panel}.dtb', body)
                self.assertIn('linux /Image root=PARTLABEL=userdata rw rootwait rootfstype=ext4 steamos.bootlabel=super', body)
                self.assertIn('firmware_class.path=/usr/lib/firmware/steamos-arm/tb321fu', body)
            for obsolete in ('linuxdirect', 'chainloader', 'QCOMRAMP', 'usbimage', 'STORAGE', 'initrd ', ' quiet'):
                self.assertNotIn(obsolete, config)
            self.assertIn('set timeout=-1', config)
            self.assertEqual(sum(title.startswith('Logs ') for title, _ in entries), 5)
            self.assertIn('search --no-floppy --label userdata --set=ud', config)
            self.assertEqual((root / 'EFI/BOOT/grub.cfg').read_text(),
                             'configfile /boot/grub/grub.cfg\n')
            self.assertTrue((root / 'debug').exists())


if __name__ == '__main__':
    unittest.main()
