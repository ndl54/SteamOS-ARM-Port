#!/bin/bash
# Lenovo Legion Y700 Gen 5 test package, in the build VM:
#
#   mk-gen5-test.sh BASE_USERDATA.simg OUT_DIR N
#
# BASE_USERDATA is a Legion Y700 Gen 4 system (8 Elite rootfs, same as the
# Gen 5's userspace needs) from mk-tablet-flash-images / the Gen 4 test
# builds. Builds our Gen 5 kernel, turns that system into the Gen 5 one
# (install-baldur.sh) and writes:
#   steamos-gen5-card.img  GPT: steamos-gen5-logs (FAT, 256 MiB: firmware,
#                          the Android image hash, boot logs) + steamos-gen5
#                          (ext4, the system; grows to the card on first boot)
#   Image-gen5             the kernel (the installer packs it into the owner's
#                          own boot image)
#   install-gen5.sh, boot-repack.py, firmware.tsv, switch-to-steamos/
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$(readlink -f "${1:?base userdata.simg}")"; O="${2:?out dir}"; N="${3:?test number}"
KO=/work/kernel-baldur/kout; LAD=/work/kernel-baldur/ladspa
[[ "$N" =~ ^[0-9]+$ ]] || { echo "invalid test number" >&2; exit 2; }
[[ ! -e "$O" ]] || { echo "output already exists: $O" >&2; exit 1; }
mkdir -p "$O"; O=$(readlink -f "$O")
M=$(mktemp -d /mnt/gen5.XXXXXX); FSLOOP=""; LP=""; mounted=0
cleanup() {
  rc=$?
  trap - EXIT
  if [[ $mounted == 1 ]]; then
    umount "$M" || { echo "owned mount retained: $M" >&2; exit 1; }
  fi
  for loop in "$LP" "$FSLOOP"; do
    [[ -z "$loop" ]] || losetup -d "$loop" || { echo "owned loop retained: $loop" >&2; exit 1; }
  done
  rmdir "$M" || exit 1
  exit "$rc"
}
trap cleanup EXIT
fail() { echo "CHECK FAILED: $*" >&2; exit 1; }
cd "$SRC"

echo "== kernel $(date +%T)"
initrd=/work/kernel-elden/initramfs/initrd.cpio
cpio -i --to-stdout './init' < "$initrd" | cmp - external-and-mods/kernel-common/initramfs/init || fail "stale initramfs (rebuild kernel-elden first)"
bash scripts/build-baldur-kernel.sh $KO "$initrd" > /work/kbaldur.log 2>&1 || { tail -40 /work/kbaldur.log; fail "kernel"; }
kr=$(basename "$(ls -d $KO/modules/*)")
[ "$(strings $KO/boot/Image | grep -c "root=PARTLABEL=steamos-gen5")" -gt 0 ] || fail "cmdline"

echo "== speaker filter plugins $(date +%T)"
rm -rf $LAD; mkdir -p $LAD
docker run --rm --platform linux/arm64 -v $LAD:/out ubuntu:24.04 bash -c '
  set -e; apt-get -qq update >/dev/null; cd /tmp && apt-get -qq download swh-plugins >/dev/null
  dpkg-deb -x swh-plugins_*.deb x; cp x/usr/lib/ladspa/sc4_1882.so x/usr/lib/ladspa/fast_lookahead_limiter_1913.so /out/'
[ -s $LAD/sc4_1882.so ] && [ -s $LAD/fast_lookahead_limiter_1913.so ] || fail "ladspa"

echo "== system $(date +%T)"
simg2img "$BASE" "$O/fs.img"
FSLOOP=$(losetup -f --show "$O/fs.img")
mount "$FSLOOP" "$M"; mounted=1
R=$M
bash scripts/install-baldur.sh $R $KO $LAD
# What changed for the tablets since the base was built.
OV=steamos-overlay
install -m0755 $OV/usr/lib/steamos/gamescope-session $R/usr/lib/steamos/gamescope-session
install -m0755 $OV/usr/bin/steamos-session-select $R/usr/bin/steamos-session-select
install -m0755 sm8750-overlay/usr/lib/odin3/odin3d $R/usr/lib/odin3/odin3d
install -m0644 $OV/usr/lib/systemd/system/steamos-arm-gen5-sd-grow.service $OV/usr/lib/systemd/system/steamos-arm-tablet-charge-full.service $R/usr/lib/systemd/system/
HC=$(find $M -maxdepth 6 -type d -path "*homebrew/plugins/konkr-control" | head -1)
[ -n "$HC" ] || fail "Handheld Control"
install -m0644 external-and-mods/Decky/sm8650/konkr-control/main.py $HC/main.py
install -m0644 external-and-mods/Decky/sm8650/konkr-control/dist/index.js $HC/dist/index.js
chown -R 1000:1000 $HC
echo "== check"
[ -f $R/usr/lib/modules/$kr/modules.dep ] && ls $R/usr/lib/modules/$kr/extra/*aw882xx* >/dev/null || fail "modules"
[ "$(ls $R/usr/lib/modules)" = "$kr" ] || fail "other kernels' modules left"
grep -q steamos-gen5 $R/etc/fstab || fail "fstab"
for u in steamos-arm-gen5-firstboot steamos-arm-gen5-emergency-key steamos-arm-gen5-sd-grow; do
  ls $R/usr/lib/systemd/system/*.wants/$u.service >/dev/null 2>&1 || fail "$u not enabled"
done
for u in tb323fu-dsp tb323fu-audio tb323fu-gen-ids tb323fu-btaddr tb323fu-usb-port; do
  [ -L $R/etc/systemd/system/multi-user.target.wants/$u.service ] && [ -f $R/usr/lib/systemd/system/$u.service ] || fail "$u not enabled"
done
[ -f $R/usr/share/alsa/ucm2/Lenovo/TB323FU/HiFi.conf ] && [ -f $R/usr/share/pipewire/pipewire.conf.d/60-tb323fu-speakers.conf ] || fail "audio platform files"
[ -f $R/usr/lib/ladspa/sc4_1882.so ] && [ -f $R/usr/lib/firmware/qcom/kaanapali/LENOVO-TB323FU-tplg.bin ] || fail "speaker filter / topology"
[ "$(readlink $R/etc/systemd/system/rmtfs.service)" = /dev/null ] || fail "modem not masked"
grep -q 'GAMESCOPE_ORIENTATION=right' $R/etc/systemd/user/gamescope-session.service.d/99-zz-gen5.conf || fail "orientation"
grep -q baldur $R/usr/bin/steamos-session-select && grep -q baldur $R/usr/lib/steamos/gamescope-session && grep -q gen5 $HC/main.py || fail "tablet integration"
[ -x $R/usr/lib/steamos-arm/gen5-android ] && [ -x $R/usr/lib/hwsupport/steamos-powerbuttond ] || fail "switching / power button"
chroot $R sh -c 'command -v sfdisk && command -v partx && command -v resize2fs && command -v pkexec' >/dev/null || fail "tools"
echo "system checks ok"
sync; umount "$M"; mounted=0
losetup -d "$FSLOOP"; FSLOOP=""
e2fsck -fy "$O/fs.img" || [ $? -le 1 ]
resize2fs -M "$O/fs.img" >/dev/null
fsb=$(stat -c %s "$O/fs.img")

echo "== card image $(date +%T)"
img="$O/steamos-gen5-card.img"
truncate -s $(( 1048576 + 256*1048576 + fsb + 2*1048576 )) "$img"
sgdisk -o -n 1:2048:+256M -t 1:0700 -c 1:steamos-gen5-logs -n 2:0:+$(( fsb / 1024 ))K -t 2:8300 -c 2:steamos-gen5 "$img" >/dev/null
LP=$(losetup -fP --show "$img")
mkfs.vfat -F 32 -n GEN5LOGS ${LP}p1 >/dev/null
dd if="$O/fs.img" of=${LP}p2 bs=4M conv=sparse status=none
e2fsck -fn ${LP}p2 >/dev/null || fail "card system partition"
losetup -d "$LP"; LP=""; rm -f "$O/fs.img"
sgdisk -p "$img" | tail -3

echo "== package $(date +%T)"
cp $KO/boot/Image "$O/Image-gen5"
cp scripts/gen5/install-gen5.sh scripts/gen5/boot-repack.py external-and-mods/baldur/firmware.tsv "$O/"
cp -r external-and-mods/baldur/switch-to-steamos "$O/"
cd "$O"; sha256sum Image-gen5 steamos-gen5-card.img > SHA256SUMS; cat SHA256SUMS
f=steamos-arm-port-lenovo-legion-y700-gen5-v1.3.0-test$N.7z
rm -f ../$f; 7z a -mx=3 -mmt=8 ../$f Image-gen5 steamos-gen5-card.img install-gen5.sh boot-repack.py firmware.tsv switch-to-steamos SHA256SUMS >/dev/null
cd ..; sha256sum $f | tee $f.sha256; ls -l $f
echo "==> done $(date +%T)"
