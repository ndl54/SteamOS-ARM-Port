#!/usr/bin/env python3
"""Stage source runtime delta on a private repack image, recording every byte.

The baseline's embedded source SHA selects the delta; never touches the baseline.
This is not a general installer or an OTA operation.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main(root, home, manifest):
    assert root != Path('/') and (root/'usr/bin').is_dir()
    base = json.loads((root/'usr/lib/steamos-arm/pocketevo-build.json').read_text())['source_commit']
    subprocess.run(['git','-C',str(REPO),'cat-file','-e',base+'^{commit}'],check=True)
    records = {}
    def copy(src, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Replace leaf symlinks instead of following absolute target-root links.
        if dest.is_symlink(): dest.unlink()
        if src.is_symlink():
            if dest.exists(): dest.unlink()
            dest.symlink_to(os.readlink(src))
            value = {'symlink': os.readlink(src)}
        else:
            shutil.copyfile(src, dest)
            shutil.copymode(src, dest)
            value = {'sha256': sha(src)}
            assert sha(dest) == value['sha256']
            if src.suffix == '.py':
                for cache in (dest.parent/'__pycache__').glob(dest.stem+'.*.pyc'):
                    cache.unlink()
                dest.with_suffix('.pyc').unlink(missing_ok=True)
        records[str(dest.relative_to(root)) if dest.is_relative_to(root) else 'HOME/'+str(dest.relative_to(home))] = {'source':str(src.relative_to(REPO)),**value}
    overlays = ['steamos-overlay','sm8650-overlay','sm8550-overlay','dualscreen-overlay']
    for overlay in overlays:
        raw = subprocess.check_output(['git','-C',str(REPO),'diff','--name-only','-z',base,'HEAD','--',overlay])
        for name in raw.decode().split('\0'):
            if not name: continue
            src = REPO/name
            rel = Path(name).relative_to(overlay)
            if not src.exists() and not src.is_symlink():
                raise RuntimeError('Explicit deletion review required: '+name)
            copy(src, root/rel)
            if rel.parts[0] == 'etc':
                upper = root/'var/lib/overlays/etc/upper'
                if upper.is_dir(): copy(src, upper/Path(*rel.parts[1:]))
    # These vendor application files have stable installed locations in the base.
    for srcdir, destdir in [
        ('external-and-mods/NO_Steam','usr/share/no-steam-games'),
        ('external-and-mods/ufs-install','usr/share/easy-ufs-install'),
        ('external-and-mods/konkr-update','usr/share/konkr-update'),
    ]:
        names = subprocess.check_output(['git','-C',str(REPO),'ls-files','-z',srcdir]).decode().split('\0')
        for name in filter(None,names): copy(REPO/name,root/destdir/Path(name).relative_to(srcdir))
    policy='external-and-mods/ufs-install/polkit/org.steamos-arm.easy-ufs-install.policy'
    copy(REPO/policy,root/'usr/share/polkit-1/actions/org.steamos-arm.easy-ufs-install.policy')
    # Tracked dist is the shipped implementation for these plugins.
    plugins=REPO/'external-and-mods/Decky/Plug-ins/homebrew/plugins'
    changed=subprocess.check_output(['git','-C',str(REPO),'diff','--name-only','-z',base,'HEAD','--',str(plugins.relative_to(REPO))]).decode().split('\0')
    for name in filter(None,changed):
        src=REPO/name; rel=src.relative_to(plugins)
        copy(src,root/'usr/share/steamos-odin/decky-plugins'/rel)
        copy(src,home/'steamos/homebrew/plugins'/rel)
    # The seeded RUNSTEAM copy otherwise shadows the new system script.
    seeded=home/'steamos/.local/share/Steam/RUNSTEAM.sh'
    if seeded.exists(): copy(REPO/'steamos-overlay/usr/share/deckard/RUNSTEAM.sh',seeded)
    for etc in (root/'etc', root/'var/lib/overlays/etc/upper'):
        if not etc.is_dir(): continue
        for unit in ('steamos-arm-os-release.service','steamos-arm-panel-calibration.service'):
            link=etc/'systemd/system/multi-user.target.wants'/unit
            link.parent.mkdir(parents=True,exist_ok=True)
            link.unlink(missing_ok=True); link.symlink_to('/usr/lib/systemd/system/'+unit)
        subprocess.run([sys.executable,str(REPO/'scripts/configure-upower.py'),str(etc/'UPower/UPower.conf')],check=True)
    for f in ('usr/lib/qt6/plugins/discover/packagekit-backend.so','usr/lib/qt6/plugins/discover-notifier/DiscoverPackageKitNotifier.so'):
        (root/f).unlink(missing_ok=True)
    manifest.write_text(json.dumps({'baseline_source':base,'source_commit':subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),'files':records},indent=2)+'\n')
    print(f'Staged and compared {len(records)} runtime paths')

if __name__ == '__main__': main(*(Path(p).resolve() for p in sys.argv[1:]))
