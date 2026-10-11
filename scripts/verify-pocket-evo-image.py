#!/usr/bin/env python3
"""Read-only verification of mounted image contents; never runs a compositor."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify(root, boot, home, kernel, gamescope):
    krel = kernel.name
    checked = {}

    def same(actual, expected):
        assert digest(actual) == digest(expected), str(actual)
        checked[str(actual)] = digest(actual)

    def source(path):
        same(root / path.split('/', 1)[1], REPO / path)

    # Only the two Android v0 command-line fields may differ from the tested boot blob.
    actual = bytearray((boot/'KERNEL').read_bytes())
    expected = (kernel/'boot/KERNEL').read_bytes()
    assert actual[:8] == b'ANDROID!'
    assert struct.unpack_from('<I', actual, 40)[0] == 0
    cmdline = actual[64:576].split(b'\0')[0] + actual[608:1632].split(b'\0')[0]
    partuuid = subprocess.check_output(['findmnt', '-no', 'SOURCE', str(root)], text=True).strip()
    partuuid = subprocess.check_output(['blkid', '-s', 'PARTUUID', '-o', 'value', partuuid], text=True).strip()
    assert ('root=PARTUUID=' + partuuid).encode() in cmdline
    for start, end in ((64, 576), (608, 1632)):
        actual[start:end] = expected[start:end]
    assert actual == expected, 'Boot payload/header differs from tested kernel'
    subprocess.run(['md5sum', '-c', 'KERNEL.md5'], cwd=boot, check=True, capture_output=True)
    same(root/f'usr/lib/modules/{krel}/config', kernel/f'config-{krel}')
    for p in (kernel/f'modules/{krel}').rglob('*.ko*'):
        same(root/'usr/lib/modules'/krel/p.relative_to(kernel/'modules'/krel), p)
    for p in (kernel/'firmware').rglob('*'):
        if p.is_file() and not p.is_symlink():
            same(root/'usr/lib/firmware'/p.relative_to(kernel/'firmware'), p)
    assert (root/f'usr/lib/modules/{krel}/modules.dep').stat().st_size

    for prefix in ('usr', 'usr/local'):
        for b in ('gamescope', 'gamescopectl', 'gamescopereaper', 'gamescopestream'):
            same(root/prefix/'bin'/b, gamescope/'src'/b)
        caps = subprocess.check_output(['getcap', str(root/prefix/'bin/gamescope')], text=True)
        assert caps.strip().endswith('cap_sys_nice=eip'), caps
        same(root/prefix/'lib/libVkLayer_FROG_gamescope_wsi_aarch64.so', gamescope/'layer/libVkLayer_FROG_gamescope_wsi_aarch64.so')
        for section in ('scripts', 'looks'):
            for p in (REPO/'external-and-mods/gamescope'/section).rglob('*'):
                if p.is_file():
                    same(root/prefix/'share/gamescope'/p.relative_to(REPO/'external-and-mods/gamescope'), p)
    manifest = json.loads((root/'usr/share/vulkan/implicit_layer.d/VkLayer_FROG_gamescope_wsi.aarch64.json').read_text())
    assert (root/manifest['layer']['library_path'].lstrip('/')).is_file()
    same(root/'usr/bin/inputplumber', REPO/'external-and-mods/InputPlumber/inputplumber-0.81.0-konkr')
    for path in (
        'steamos-overlay/usr/lib/steamos/gamescope-session',
        'steamos-overlay/usr/lib/steamos/sm8550-audio-pipewire',
        'steamos-overlay/usr/lib/steamos-arm/steamos-arm-wifi-wake',
        'sm8650-overlay/usr/lib/konkr/konkr-sleep',
        'sm8550-overlay/usr/lib/pocketevo/pocket-evo-sleep',
        'sm8550-overlay/usr/lib/pocketevo/pocket-evo-wifi-wake',
        'sm8550-overlay/usr/lib/pocketevo/pocket-evo-controller',
        'sm8550-overlay/usr/lib/pocketevo/pocket-evo-power',
        'sm8550-overlay/usr/lib/pocketevo/pocket_evo_led.py',
        'sm8550-overlay/usr/lib/systemd/system/konkr-sleep.service.d/50-pocket-evo.conf',
        'sm8550-overlay/usr/lib/systemd/user-generators/pocket-evo-portal',
        'sm8550-overlay/usr/share/alsa/ucm2/AYANEO/PocketEVO/HiFi.conf',
        'sm8550-overlay/usr/share/alsa/ucm2/conf.d/sm8550/ayaneo-AYANEOPocketEVO-.conf',
    ):
        source(path)
    for unit, target in (
        ('pocket-evo-led.service', 'multi-user'),
        ('pocket-evo-led-sleep.service', 'sleep'),
        ('pocket-evo-controller.service', 'multi-user'),
        ('pocket-evo-power.service', 'multi-user'),
    ):
        source('sm8550-overlay/usr/lib/systemd/system/' + unit)
        for etc in (root/'etc', root/'var/lib/overlays/etc/upper'):
            if not etc.exists():
                continue
            link = etc/f'systemd/system/{target}.target.wants'/unit
            assert link.is_symlink() and os.readlink(link) == '/usr/lib/systemd/system/' + unit, link
    for etc in (root/'etc', root/'var/lib/overlays/etc/upper'):
        if etc.exists():
            for p in (REPO/'sm8550-overlay/etc/inputplumber').rglob('*.yaml'):
                same(etc/'inputplumber'/p.relative_to(REPO/'sm8550-overlay/etc/inputplumber'), p)
    for p in (REPO/'sm8550-overlay/etc/inputplumber/capability_maps.d').glob('*.yaml'):
        same(root/'usr/share/inputplumber/capability_maps'/p.name, p)
    for dest in (root/'usr/share/steamos-odin/decky-plugins/konkr-control', home/'steamos/homebrew/plugins/konkr-control'):
        for f in ('main.py', 'plugin.json', 'package.json', 'dist/index.js'):
            same(dest/f, REPO/'external-and-mods/Decky/sm8650/konkr-control'/f)
    assert (home/'steamos').stat().st_uid == (home/'steamos/homebrew/plugins/konkr-control').stat().st_uid
    for path, sha in json.loads((REPO/'docs/audit/pocket-evo-preserved-files.json').read_text()).items():
        assert digest(REPO/path) == sha, path

    # CLI/library checks in the actual image, no real devices or compositor.
    # no-new-privs prevents the file capability from requesting privileges the
    # builder does not have; its on-disk value is checked independently above.
    run = ['setpriv', '--no-new-privs', str(root/'usr/bin/bwrap'),
           '--ro-bind', str(root), '/', '--dev', '/dev', '--proc', '/proc',
           '--tmpfs', '/tmp', '--tmpfs', '/run', '--unshare-pid', '--die-with-parent',
           '--setenv', 'PATH', '/usr/local/bin:/usr/bin']
    runtime = {}
    for exe in ('/usr/bin/gamescope', '/usr/local/bin/gamescope', '/usr/bin/inputplumber'):
        runtime[exe] = subprocess.check_output(run + [exe, '--version'], stderr=subprocess.STDOUT, text=True).strip()
    for exe in ('gamescope', 'gamescopectl', 'gamescopereaper', 'gamescopestream'):
        for prefix in ('usr', 'usr/local'):
            path = f'/{prefix}/bin/{exe}'
            deps = subprocess.check_output(run + ['/usr/bin/ldd', '-r', path], stderr=subprocess.STDOUT, text=True)
            assert 'not found' not in deps and 'undefined symbol' not in deps, deps
    for path in ('/usr/bin/inputplumber', '/usr/lib/libVkLayer_FROG_gamescope_wsi_aarch64.so', '/usr/local/lib/libVkLayer_FROG_gamescope_wsi_aarch64.so'):
        deps = subprocess.check_output(run + ['/usr/bin/ldd', '-r', path], stderr=subprocess.STDOUT, text=True)
        assert 'not found' not in deps and 'undefined symbol' not in deps, deps
    return {'result': 'PASS', 'hardware': 'not tested', 'kernel_release': krel,
            'boot_payload': 'identical to tested kernel except preserved root cmdline',
            'runtime_versions': runtime, 'files_compared': len(checked),
            'capabilities': 'cap_sys_nice=eip at both Gamescope paths',
            'led_rgb': '10 protected source hashes and installed LED/plugin bytes unchanged',
            'service_links': 'root and persistent etc verified', 'runtime_files_sha256': checked}


if __name__ == '__main__':
    print(json.dumps(verify(*(Path(x).resolve() for x in sys.argv[1:])), indent=2))
