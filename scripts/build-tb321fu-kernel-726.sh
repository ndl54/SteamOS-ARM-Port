#!/bin/bash
# Lenovo Legion Y700 Gen 3 (TB321FU) kernel from the 7.2.6 tree that boots on
# the tablet: kernel.org 7.2.6, the tablet patch series and device trees from
# github.com/enij90/armada-tb321fu (packages/kernel, pinned below), arm64
# defconfig plus its config fragment. On top: our startup code built in (the
# GRUB entry passes no initrd), a CSOT copy of the device tree (the series'
# panel driver has both panels, its device tree only selects BOE) and a
# neutral version suffix.
#
#   build-tb321fu-kernel-726.sh OUT_DIR INITRD_CPIO
#
# OUT_DIR gets the layout mk-tablet-flash-images.sh takes as KERNEL_OUT:
# boot/Image, dtbs/sm8650-lenovo-tb321fu-{boe,csot}.dtb, modules/<kver>/,
# config-<kver>. Runs as root in the build VM (docker, fedora:43). FAST=1
# reuses a prepared build tree from this pinned recipe and re-merges config.
set -euo pipefail
OUT="${1:?output dir}"; CPIO="$(readlink -f "${2:?initrd.cpio}")"
SRC_COMMIT=62076530bf1ff34295d671016658965e54e597f1
SRC_URL="https://codeload.github.com/enij90/armada-tb321fu/tar.gz/${SRC_COMMIT}"
W="${WORK:-/work/kernel-tb321fu-726}"
die() { echo "ERROR: $*" >&2; exit 1; }
[[ -s "$CPIO" ]] || die "no $CPIO"
# The pinned builder treats any nonempty FAST as true, and skips patches
# even when it has just extracted a missing tree. Reject that unsafe case.
case "${FAST:-0}" in
  0) FAST="" ;;
  1) FAST=1 ;;
  *) die "FAST must be 0 or 1" ;;
esac
VBLANK_PATCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/../external-and-mods/kernel-sm8650/patches" && pwd)/0055-drm-msm-dpu-real-vblank-timestamps-on-command-mode-panels.patch"
recipe="$SRC_COMMIT:steamos-tablet-v1:$(sha256sum "$VBLANK_PATCH" | awk '{print $1}')"
stamp="$W/cache/steamos-tablet-recipe"
if [[ $FAST == 1 ]]; then
  [[ -f "$stamp" && "$(cat "$stamp")" == "$recipe" ]] || die "FAST=1 tree does not match this recipe; run with FAST=0 first"
  [[ -s "$W/cache/build/linux-7.2.6/.config" ]] || die "FAST=1 needs a prepared tree; run with FAST=0 first"
fi
# Invalidate before any preparation/build so a failed run cannot certify a tree.
rm -f "$stamp"
mkdir -p "$W/cache" "$W/out"
rm -rf "$W/pkg" "$W/out"/*

tarball="$W/cache/src-${SRC_COMMIT}.tar.gz"
[[ -s "$tarball" ]] || curl -fsSL --retry 3 -o "$tarball" "$SRC_URL"
mkdir -p "$W/pkg"
tar -xzf "$tarball" -C "$W/pkg" --strip-components=3 --wildcards '*/packages/kernel/*'
P="$W/pkg"
[[ -f "$P/scripts/build-kernel.sh" && -f "$P/patches/series" ]] || die "kernel package not found in the source"

dts="$P/dts/sm8650-lenovo-tb321fu.dts"
# The new pin has the TE counter path but lacks invalid-counter propagation.
# Carry the reviewed shared055 repair into this separate package's series slot.
cp "$VBLANK_PATCH" "$P/patches/0078-drm-msm-dpu-fix-vblank-timestamps-on-command-mode-panels.patch"
# Volume keys the way Android has them: the series swaps them for a
# controller grip, and in our landscape they came out reversed (test 6).
grep -q 'linux,code = <KEY_VOLUMEDOWN>;' "$dts" && grep -q 'linux,code = <KEY_VOLUMEUP>;' "$dts" || die "volume keys not found"
sed -i -e 's/linux,code = <KEY_VOLUMEDOWN>;/linux,code = <KEY_VOLUME_SWAP>;/' \
       -e 's/linux,code = <KEY_VOLUMEUP>;/linux,code = <KEY_VOLUMEDOWN>;/' \
       -e 's/linux,code = <KEY_VOLUME_SWAP>;/linux,code = <KEY_VOLUMEUP>;/' "$dts"
awk '/key-volume-up/ {f=1} f && /linux,code/ {print; exit}' "$dts" | grep -q KEY_VOLUMEUP || die "volume keys not swapped back"
# CSOT: the same board with the CSOT panel selected; BOE keeps the file as is.
sed -e 's/kirby-nt36523-boe-dsc/kirby-nt36523-csot-dsc/g' \
    -e 's/kirby_nt36523_boe_dsc_vid/kirby_nt36523_csot_dsc_vid/' \
    -e 's/novatek_ts_boe_fw.bin/novatek_ts_csot_fw.bin/g' \
    -e 's|^\(\s*model = "\)Lenovo Legion Y700 (2025) / TB321FU"|\1Lenovo Legion Y700 Gen 3 (CSOT panel)"|' \
    "$dts" > "$P/dts/sm8650-lenovo-tb321fu-csot.dts"
grep -q 'kirby-nt36523-csot-dsc-vid' "$P/dts/sm8650-lenovo-tb321fu-csot.dts" || die "CSOT panel not selected"
grep -q 'novatek_ts_csot_fw.bin' "$P/dts/sm8650-lenovo-tb321fu-csot.dts" || die "CSOT touch firmware not selected"
! grep -q 'boe-dsc\|novatek_ts_boe_fw' "$P/dts/sm8650-lenovo-tb321fu-csot.dts" || die "BOE left in the CSOT device tree"

cp "$CPIO" "$P/initrd.cpio"
cat >> "$P/config/armada-kernel.config.overrides" <<EOF

# SteamOS ARM Port: startup code built in, our version suffix
CONFIG_INITRAMFS_SOURCE="/src/initrd.cpio"
CONFIG_INITRAMFS_COMPRESSION_NONE=y
# /etc must be mounted before systemd starts; our initramfs has no modules.
CONFIG_OVERLAY_FS=y
CONFIG_BLK_DEV_LOOP=y
CONFIG_LOCALVERSION="-tb321fu"
# CONFIG_LOCALVERSION_AUTO is not set
CONFIG_FONTS=y
CONFIG_FONT_TER16x32=y
EOF

docker run --rm -v "$P:/src" -v "$W/out:/work/out" -v "$W/cache:/cache" -w /src \
  -e KBUILD_BUILD_USER=steamos -e KBUILD_BUILD_HOST=builder -e FAST="${FAST:-}" \
  fedora:43 bash -c '
    set -e
    dnf -q -y install gcc binutils make bc bison flex openssl-devel elfutils-libelf-devel \
      dwarves zstd xz cpio patch curl perl-interpreter python3 findutils diffutils gawk \
      grep sed coreutils hostname gzip tar kmod >/dev/null
    WORK_DIR=/cache/build OUT_DIR=/work/out bash scripts/build-kernel.sh
  '

printf '%s\n' "$recipe" > "$stamp"

pkg=$(ls "$W"/out/*.tar.zst | head -1)
[[ -s "$pkg" ]] || die "no kernel package built"
rm -rf "$W/stage"; mkdir -p "$W/stage"
zstd -dc "$pkg" | tar -xf - -C "$W/stage"
# The pinned builder computes kernelrelease after merging the config, so
# Image, DTBs and modules share the final release directory.
st="$W/stage/lib/modules"
kver=$(basename "$(dirname "$(ls "$st"/*/modules.dep | head -1)")")
img=$(ls "$st"/*/vmlinuz | head -1); dtbd=$(dirname "$(ls "$st"/*/dtb/qcom/sm8650-lenovo-tb321fu.dtb | head -1)")
rm -rf "$OUT"; mkdir -p "$OUT/boot" "$OUT/dtbs" "$OUT/modules"
cp "$img" "$OUT/boot/Image"
cp "$dtbd/sm8650-lenovo-tb321fu.dtb" "$OUT/dtbs/sm8650-lenovo-tb321fu-boe.dtb"
cp "$dtbd/sm8650-lenovo-tb321fu-csot.dtb" "$OUT/dtbs/sm8650-lenovo-tb321fu-csot.dtb"
m="$st/$kver"
rm -rf "$m/dtb" "$m/vmlinuz" "$m/.armada-source"
mv "$m" "$OUT/modules/$kver"
cp "$W/cache/build/linux-"*/.config "$OUT/config-$kver"
grep -q 'steamos.bootlabel' "$OUT/boot/Image" || die "startup code isn't in the Image"
echo "kernel $kver -> $OUT"
ls -l "$OUT/boot" "$OUT/dtbs"
