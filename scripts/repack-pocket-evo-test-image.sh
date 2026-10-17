#!/bin/bash
# Run inside the existing pocket-evo-build container; see docs/pocket-evo-led.md.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_commit=$(git -C "$ROOT" rev-parse HEAD)
[[ -z $(git -C "$ROOT" status --porcelain --untracked-files=no) ]]
base_image=${BASE_IMAGE:-$(cat /work/image-path)}
output=$(readlink -f "${KERNEL_OUTPUT:?set KERNEL_OUTPUT to the validated kernel output}")
GSBUILD=${GAMESCOPE_BUILD:?set GAMESCOPE_BUILD to the validated Gamescope build}
krel=$(basename "$output")
[[ $krel == 7.2.8-pocketevo-steamos ]]
[[ -s $output/boot/KERNEL && -d $output/modules/$krel ]]
# mkdir is intentionally exclusive: never overwrite an earlier image or logs.
ART=${IMAGE_OUTPUT_DIR:-/artifacts/image-final-$(date -u +%Y%m%d-%H%M%S)-${source_commit:0:7}}
mkdir "$ART"
ART=$(readlink -f "$ART")
exec > >(tee "$ART/image-build.log") 2>&1
export ART
python3 /src/scripts/verify-pocket-evo-kernel.py /work/kernel-pocketevo/linux-7.2.8 "$output"
work=$(mktemp -d /work/pocketevo-image.XXXXXX)
mnt=$work/mnt
mkdir -p "$mnt/boot" "$mnt/root" "$mnt/home"
export IMAGE_MOUNT=$mnt
image=$work/image.img
base_sha=$(sha256sum "$base_image" | awk '{print $1}')
printf '%s  %s\n' "$base_sha" "$base_image" > "$ART/base-image.sha256"
cp --reflink=auto --sparse=always "$base_image" "$image"
[[ $(sha256sum "$image" | awk '{print $1}') == "$base_sha" ]]
export BASE_IMAGE_SHA256=$base_sha GAMESCOPE_BUILD=$GSBUILD KERNEL_OUTPUT=$output
loop=$(losetup --find --show --partscan "$image")
cleanup() {
  umount "${mnt}/home" 2>/dev/null || true
  umount "${mnt}/root" 2>/dev/null || true
  umount "${mnt}/boot" 2>/dev/null || true
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
mount "${loop}p1" "${mnt}/boot"
mount "${loop}p2" "${mnt}/root"
mkdir -p "${mnt}/home"
mount "${loop}p3" "${mnt}/home"
export NEW_KERNEL="$output/boot/KERNEL"
export ROOT_PARTUUID=$(blkid -s PARTUUID -o value "${loop}p2")
python3 - <<'PY'
import os, struct
from pathlib import Path
old = (Path(os.environ['IMAGE_MOUNT']) / 'boot/KERNEL').read_bytes()
new = bytearray(Path(os.environ['NEW_KERNEL']).read_bytes())
assert old[:8] == new[:8] == b'ANDROID!'
assert struct.unpack_from('<I', old, 36)[0] == struct.unpack_from('<I', new, 36)[0] == 2048
assert struct.unpack_from('<I', new, 40)[0] == 0
cmdline = old[64:576].split(b'\0')[0] + old[608:1632].split(b'\0')[0]
assert ('root=PARTUUID=' + os.environ['ROOT_PARTUUID']).encode() in cmdline
# Keep all released boot flags, including the root partition identity.
new[64:576] = old[64:576]
new[608:1632] = old[608:1632]
(Path(os.environ['IMAGE_MOUNT']) / 'boot/KERNEL').write_bytes(new)
(Path(os.environ['ART']) / 'boot-cmdline.txt').write_text(cmdline.decode() + '\n')
print('Preserved release cmdline:', cmdline.decode())
PY
(cd "${mnt}/boot" && md5sum KERNEL > KERNEL.md5 && md5sum -c KERNEL.md5)
rsync -a "$output/modules/$krel/" "${mnt}/root/usr/lib/modules/$krel/"
rsync -a "$output/firmware/" "${mnt}/root/usr/lib/firmware/"
depmod -b "${mnt}/root" "$krel"
install -m644 "$output/config-$krel" "${mnt}/root/usr/lib/modules/$krel/config"
install -m644 "$output/System.map-$krel" "${mnt}/root/usr/lib/modules/$krel/System.map"
for entry in \
  steamos-overlay/usr/lib/steamos/sm8550-audio-pipewire \
  steamos-overlay/usr/lib/steamos-arm/steamos-arm-wifi-wake \
  sm8650-overlay/usr/lib/konkr/konkr-sleep; do
  dest=${entry#*/}
  install -m755 "/src/$entry" "${mnt}/root/$dest"
  cmp "/src/$entry" "${mnt}/root/$dest"
done
bash /src/scripts/install-pocket-evo-display.sh "${mnt}/root" "$GSBUILD"
# Reuse the existing InputPlumber installation; update its validated binary/maps.
(cd /src/external-and-mods/InputPlumber && sha256sum -c inputplumber-0.81.0-konkr.sha256)
install -m755 /src/external-and-mods/InputPlumber/inputplumber-0.81.0-konkr "${mnt}/root/usr/bin/inputplumber"
for etc in "${mnt}/root/etc" "${mnt}/root/var/lib/overlays/etc/upper"; do
  [[ -d "$etc" ]] || continue
  mkdir -p "$etc/inputplumber"
  cp -r --no-preserve=mode,ownership /src/sm8550-overlay/etc/inputplumber/. "$etc/inputplumber/"
done
cp /src/sm8550-overlay/etc/inputplumber/capability_maps.d/*.yaml "${mnt}/root/usr/share/inputplumber/capability_maps/"
bash /src/scripts/install-pocket-evo-platform.sh "${mnt}/root"
install -m755 /src/external-and-mods/kernel-common/initramfs/bootdebug "${mnt}/root/usr/lib/steamos-arm/bootdebug"
bash /src/scripts/install-pocket-evo-led.sh "${mnt}/root"
bash /src/scripts/install-pocket-evo-sleep.sh "${mnt}/root"
plugin=/src/external-and-mods/Decky/sm8650/konkr-control
for dest in "${mnt}/root/usr/share/steamos-odin/decky-plugins/konkr-control" "${mnt}/home/steamos/homebrew/plugins/konkr-control"; do
  mkdir -p "$dest/dist"
  for file in main.py plugin.json package.json dist/index.js; do
    install -m644 "$plugin/$file" "$dest/$file"
    cmp "$plugin/$file" "$dest/$file"
  done
done
# Preserve the released home directory ownership, including nonstandard UIDs.
chown -R --reference="${mnt}/home/steamos" "${mnt}/home/steamos/homebrew/plugins/konkr-control"
touch "${mnt}/boot/debug"
cp "$output/config-$krel" "$ART/"
SOURCE_COMMIT=$source_commit KREL=$krel python3 - <<'PY'
import hashlib, json, os, subprocess
from datetime import datetime, timezone
from pathlib import Path
root = Path(os.environ['IMAGE_MOUNT']) / 'root'
files = [
 'usr/bin/gamescope',
 'usr/bin/inputplumber',
 'usr/lib/libVkLayer_FROG_gamescope_wsi_aarch64.so',
 'usr/lib/steamos/gamescope-session',
 'usr/lib/pocketevo/pocket-evo-controller',
 'usr/lib/pocketevo/pocket-evo-power',
 'usr/lib/systemd/system/pocket-evo-controller.service',
 'usr/lib/systemd/system/pocket-evo-power.service',
 'usr/share/gamescope/scripts/10-steamos-arm/pocket-evo.icna3512.lua',
 'usr/lib/steamos/sm8550-audio-pipewire',
 'usr/lib/steamos-arm/steamos-arm-wifi-wake',
 'usr/lib/konkr/konkr-sleep',
 'usr/lib/pocketevo/pocket_evo_led.py',
 'usr/lib/pocketevo/pocket-evo-sleep',
 'usr/lib/pocketevo/pocket-evo-usb-sleep',
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
 'base_image_sha256': os.environ['BASE_IMAGE_SHA256'],
 'gamescope_version': '3.16.30-steamos-arm',
 'gamescope_source_commit': '3ad7c44339521e010fdf4e8471abb24174265f52',
 'inputplumber_version': '0.81.0 with AYANEO polling and target-switch fixes',
 'base_release': 'hashtagbasit/SteamOS-ARM-Port v1.3.2 SM8550',
 'base_os_release': (root/'etc/os-release').read_text(),
 'kernel_release': os.environ['KREL'],
 'kernel_recipe': 'kernel-pocketevo, Linux 7.2.8, GCC 15',
 'dtb': 'qcs8550-ayaneo-pocketevo',
 'rocknix_commit': subprocess.check_output(['git','-C','/work/rocknix','rev-parse','HEAD'], text=True).strip(),
 'compiler': subprocess.check_output(['gcc','--version'], text=True).splitlines()[0],
 'boot_cmdline': (Path(os.environ['ART']) / 'boot-cmdline.txt').read_text().strip(),
 'boot_kernel_sha256': hashlib.sha256((Path(os.environ['IMAGE_MOUNT']) / 'boot/KERNEL').read_bytes()).hexdigest(),
 'runtime_files_sha256': {f: hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},
 'debug_capture_enabled': True,
}
data = json.dumps(manifest, indent=2) + '\n'
(Path(os.environ['ART']) / 'build-manifest.json').write_text(data)
(Path(os.environ['IMAGE_MOUNT']) / 'boot/pocketevo-build.json').write_text(data)
(root/'usr/lib/steamos-arm/pocketevo-build.json').write_text(data)
PY
test -s "${mnt}/root/usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d/99-odin-wayland.conf"
test -x "${mnt}/root/usr/lib/systemd/user-generators/pocket-evo-portal"
test -s "${mnt}/root/usr/lib/modules/$krel/modules.dep"
for m in nf_tables nft_ct nft_nat nft_masq nft_redir nft_reject_inet nft_log nft_limit nft_fib_inet chipone_tddi; do
  modinfo -b "${mnt}/root" -k "$krel" "$m" | sed -n '1p;/^vermagic:/p'
done
python3 /src/scripts/verify-pocket-evo-image.py "${mnt}/root" "${mnt}/boot" "${mnt}/home" "$output" "$GSBUILD" > "$ART/image-verification.json"
sync
umount "${mnt}/home" "${mnt}/root" "${mnt}/boot"
fsck.fat -n "${loop}p1"
e2fsck -fn "${loop}p2"
e2fsck -fn "${loop}p3"
losetup -d "$loop"
trap - EXIT
artifact="steamos-pocketevo-v1.3.2-${source_commit:0:7}-armada-complete-test.img"
[[ $(sha256sum "$base_image" | awk '{print $1}') == "$base_sha" ]]
cp --sparse=always "$image" "$ART/$artifact.partial"
mv "$ART/$artifact.partial" "$ART/$artifact"
sha256sum "$image" | awk -v name="$artifact" '{print $1"  "name}' > "$ART/IMAGE-SHA256.txt"
(cd "$ART" && sha256sum -c IMAGE-SHA256.txt)
xz -T4 -3 -c "$ART/$artifact" > "$ART/$artifact.xz.partial"
mv "$ART/$artifact.xz.partial" "$ART/$artifact.xz"
xz -t "$ART/$artifact.xz"
# Verify decompression without writing another 19GB temporary image.
[[ $(xz -dc "$ART/$artifact.xz" | sha256sum | awk '{print $1}') == $(awk '{print $1}' "$ART/IMAGE-SHA256.txt") ]]
(cd "$ART" && sha256sum "$artifact.xz" > SHA256SUMS)
rm "$image"
rmdir "$mnt/boot" "$mnt/root" "$mnt/home" "$mnt" "$work"
ls -lh "$ART"
