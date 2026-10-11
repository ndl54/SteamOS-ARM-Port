#!/bin/bash
# Run inside the existing pocket-evo-build container; see docs/pocket-evo-led.md.
set -euo pipefail
exec > >(tee /artifacts/image-build.log) 2>&1
image=$(cat /work/image-path)
output=$(readlink -f /work/kernel-pocketevo/output/current)
krel=$(basename "$output")
source_commit=$(git -C /src rev-parse HEAD)
[[ $krel == 7.2.8-pocketevo-steamos ]]
[[ -s $output/boot/KERNEL && -d $output/modules/$krel ]]
[[ -z $(git -C /src status --porcelain --untracked-files=no) ]]
loop=$(losetup --find --show --partscan "$image")
cleanup() {
  umount /work/mnt/home 2>/dev/null || true
  umount /work/mnt/root 2>/dev/null || true
  umount /work/mnt/boot 2>/dev/null || true
  losetup -d "$loop"
}
trap cleanup EXIT
for p in 1 2 3; do
  b=${loop}p$p
  if [[ ! -b $b ]]; then
    d=$(cat /sys/class/block/${b##*/}/dev)
    mknod "$b" b "${d%:*}" "${d#*:}"
  fi
done
mount "${loop}p1" /work/mnt/boot
mount "${loop}p2" /work/mnt/root
mkdir -p /work/mnt/home
mount "${loop}p3" /work/mnt/home
export NEW_KERNEL="$output/boot/KERNEL"
export ROOT_PARTUUID=$(blkid -s PARTUUID -o value "${loop}p2")
python3 - <<'PY'
import os, struct
from pathlib import Path
old = Path('/work/original-KERNEL').read_bytes()
new = bytearray(Path(os.environ['NEW_KERNEL']).read_bytes())
assert old[:8] == new[:8] == b'ANDROID!'
assert struct.unpack_from('<I', old, 36)[0] == struct.unpack_from('<I', new, 36)[0] == 2048
assert struct.unpack_from('<I', new, 40)[0] == 0
cmdline = old[64:576].split(b'\0')[0] + old[608:1632].split(b'\0')[0]
assert ('root=PARTUUID=' + os.environ['ROOT_PARTUUID']).encode() in cmdline
# Keep all released boot flags, including the root partition identity.
new[64:576] = old[64:576]
new[608:1632] = old[608:1632]
Path('/work/mnt/boot/KERNEL').write_bytes(new)
Path('/artifacts/boot-cmdline.txt').write_text(cmdline.decode() + '\n')
print('Preserved release cmdline:', cmdline.decode())
PY
(cd /work/mnt/boot && md5sum KERNEL > KERNEL.md5 && md5sum -c KERNEL.md5)
rsync -a "$output/modules/$krel/" "/work/mnt/root/usr/lib/modules/$krel/"
rsync -a "$output/firmware/" /work/mnt/root/usr/lib/firmware/
depmod -b /work/mnt/root "$krel"
install -m644 "$output/config-$krel" "/work/mnt/root/usr/lib/modules/$krel/config"
install -m644 "$output/System.map-$krel" "/work/mnt/root/usr/lib/modules/$krel/System.map"
for entry in \
  steamos-overlay/usr/lib/steamos/sm8550-audio-pipewire \
  steamos-overlay/usr/lib/steamos-arm/steamos-arm-wifi-wake \
  sm8650-overlay/usr/lib/konkr/konkr-sleep; do
  dest=${entry#*/}
  install -m755 "/src/$entry" "/work/mnt/root/$dest"
  cmp "/src/$entry" "/work/mnt/root/$dest"
done
bash /src/scripts/install-pocket-evo-platform.sh /work/mnt/root
install -m755 /src/external-and-mods/kernel-common/initramfs/bootdebug /work/mnt/root/usr/lib/steamos-arm/bootdebug
bash /src/scripts/install-pocket-evo-led.sh /work/mnt/root
bash /src/scripts/install-pocket-evo-sleep.sh /work/mnt/root
plugin=/src/external-and-mods/Decky/sm8650/konkr-control
for dest in /work/mnt/root/usr/share/steamos-odin/decky-plugins/konkr-control /work/mnt/home/steamos/homebrew/plugins/konkr-control; do
  mkdir -p "$dest/dist"
  for file in main.py plugin.json package.json dist/index.js; do
    install -m644 "$plugin/$file" "$dest/$file"
    cmp "$plugin/$file" "$dest/$file"
  done
done
# Preserve the released home directory ownership, including nonstandard UIDs.
chown -R --reference=/work/mnt/home/steamos /work/mnt/home/steamos/homebrew/plugins/konkr-control
touch /work/mnt/boot/debug
mkdir -p /artifacts/output
cp "$output/config-$krel" /artifacts/output/
SOURCE_COMMIT=$source_commit KREL=$krel python3 - <<'PY'
import hashlib, json, os, subprocess
from datetime import datetime, timezone
from pathlib import Path
root = Path('/work/mnt/root')
files = [
 'usr/lib/steamos/sm8550-audio-pipewire',
 'usr/lib/steamos-arm/steamos-arm-wifi-wake',
 'usr/lib/konkr/konkr-sleep',
 'usr/lib/pocketevo/pocket_evo_led.py',
 'usr/lib/pocketevo/pocket-evo-sleep',
 'usr/lib/pocketevo/pocket-evo-wifi-wake',
 'usr/lib/systemd/system/konkr-sleep.service.d/50-pocket-evo.conf',
 'usr/lib/systemd/system/pocket-evo-led.service',
 'usr/lib/systemd/system/pocket-evo-led-sleep.service',
 'usr/share/steamos-odin/decky-plugins/konkr-control/main.py',
 'usr/share/steamos-odin/decky-plugins/konkr-control/dist/index.js',
 'usr/share/alsa/ucm2/AYANEO/Pocket/HiFi.conf',
 'usr/share/alsa/ucm2/AYANEO/PocketEVO/HiFi.conf',
 'usr/share/alsa/ucm2/conf.d/sm8550/ayaneo-AYANEOPocketEVO-.conf',
 'usr/lib/systemd/user-generators/pocket-evo-portal',
 'usr/lib/steamos-arm/bootdebug',
]
manifest = {
 'kind': 'Pocket EVO test image; hardware validation pending',
 'built_at_utc': datetime.now(timezone.utc).isoformat(),
 'source_repository': 'https://github.com/ndl54/SteamOS-ARM-Port',
 'source_commit': os.environ['SOURCE_COMMIT'],
 'base_release': 'hashtagbasit/SteamOS-ARM-Port v1.3.2 SM8550',
 'base_os_release': Path('/artifacts/base-os-release.txt').read_text(),
 'kernel_release': os.environ['KREL'],
 'kernel_recipe': 'kernel-pocketevo, Linux 7.2.8, GCC 15',
 'dtb': 'qcs8550-ayaneo-pocketevo',
 'rocknix_commit': subprocess.check_output(['git','-C','/work/rocknix','rev-parse','HEAD'], text=True).strip(),
 'compiler': subprocess.check_output(['gcc','--version'], text=True).splitlines()[0],
 'boot_cmdline': Path('/artifacts/boot-cmdline.txt').read_text().strip(),
 'boot_kernel_sha256': hashlib.sha256(Path('/work/mnt/boot/KERNEL').read_bytes()).hexdigest(),
 'runtime_files_sha256': {f: hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},
 'debug_capture_enabled': True,
}
data = json.dumps(manifest, indent=2) + '\n'
Path('/artifacts/output/build-manifest.json').write_text(data)
Path('/work/mnt/boot/pocketevo-build.json').write_text(data)
(root/'usr/lib/steamos-arm/pocketevo-build.json').write_text(data)
PY
test -s /work/mnt/root/usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d/99-odin-wayland.conf
test -x /work/mnt/root/usr/lib/systemd/user-generators/pocket-evo-portal
test -s "/work/mnt/root/usr/lib/modules/$krel/modules.dep"
for m in nf_tables nft_ct nft_nat nft_masq nft_redir nft_reject_inet nft_log nft_limit nft_fib_inet chipone_tddi; do
  modinfo -b /work/mnt/root -k "$krel" "$m" | sed -n '1p;/^vermagic:/p'
done
sync
umount /work/mnt/home /work/mnt/root /work/mnt/boot
fsck.fat -n "${loop}p1"
e2fsck -fn "${loop}p2"
e2fsck -fn "${loop}p3"
losetup -d "$loop"
trap - EXIT
artifact="steamos-pocketevo-v1.3.2-${source_commit:0:7}-led-test.img.xz"
sha256sum "$image" | awk -v name="${artifact%.xz}" '{print $1"  "name}' > /artifacts/output/IMAGE-SHA256.txt
xz -T6 -3 -c "$image" > "/artifacts/output/$artifact.partial"
mv "/artifacts/output/$artifact.partial" "/artifacts/output/$artifact"
xz -t "/artifacts/output/$artifact"
(cd /artifacts/output && sha256sum "$artifact" > SHA256SUMS)
xz -dc "/artifacts/output/$artifact" > "/artifacts/output/${artifact%.xz}.partial"
mv "/artifacts/output/${artifact%.xz}.partial" "/artifacts/output/${artifact%.xz}"
(cd /artifacts/output && sha256sum -c IMAGE-SHA256.txt)
ls -lh /artifacts/output
