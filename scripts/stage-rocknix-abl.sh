#!/bin/bash
# stage-rocknix-abl.sh BOOT_DIR SOC
# Put ROCKNIX ABL for SOC (sm8250, sm8550, sm8650, sm8750) and its flash/backup/
# restore scripts into BOOT_DIR/rocknix_abl/, from the release pinned
# in external-and-mods/rocknix-abl/release.env. The download is cached in
# $STEAMOS_WORK/cache and every file is checked against the pinned hashes.
set -euo pipefail
BOOT=$1
soc=${2^^}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/external-and-mods/rocknix-abl"
. "$SRC/release.env"
die() { echo "stage-rocknix-abl: $*" >&2; exit 1; }

case $soc in
  SM8250) platform=kona;      models="SM8250";          devices="Retroid Pocket 5 / Flip 2 / Mini / Mini V2, AYN Thor Lite, MANGMI Air Y Pro / Pocket Max, AYANEO Pocket MICRO 2" ;;
  SM8550) platform=kalama;    models="SM8550 QCS8550";  devices="AYN Odin 2 / Mini / Portal / Thor, AYANEO Pocket ACE / DMG / DS / EVO / S 1K / S 2K, Retroid Pocket 6 / Nova" ;;
  SM8650) platform=pineapple; models="SM8650";          devices="KONKR Pocket FIT, AYANEO Pocket S2" ;;
  SM8750) platform=sun;       models="SM8750 CQ8725S";  devices="AYN Odin 3, KONKR Pocket FIT Elite" ;;
  *) die "unknown SoC $2" ;;
esac
want_var=ABL_SHA256_$soc
want=${!want_var}

cache=${STEAMOS_WORK:-/work}/cache
mkdir -p "$cache"
tarball=$cache/$(basename "$ABL_URL")
if [[ ! -s $tarball ]] || [[ "$(sha256sum "$tarball" | cut -d' ' -f1)" != "$ABL_TARBALL_SHA256" ]]; then
  curl -fsSL -o "$tarball.part" "$ABL_URL" || die "download failed: $ABL_URL"
  mv "$tarball.part" "$tarball"
fi
[[ "$(sha256sum "$tarball" | cut -d' ' -f1)" == "$ABL_TARBALL_SHA256" ]] || die "release tarball hash mismatch"

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
tar -xzf "$tarball" -C "$tmp"
elf=$(find "$tmp" -name "abl_signed-$soc.elf" | head -1)
[[ -f $elf ]] || die "abl_signed-$soc.elf not in the release"
[[ "$(sha256sum "$elf" | cut -d' ' -f1)" == "$want" ]] || die "abl_signed-$soc.elf hash mismatch"

# Flat card/internal folder discovery and safety helpers are inlined. Emit
# the entire action as one physical shell line for root tools that start a
# fresh shell for each line. printf reconstructs only bundled literal source;
# no runtime file is sourced and no checks are split into separate processes.
out=$BOOT/rocknix_abl
# Do not recursively delete an existing folder: it may hold original ABL
# backups (including backups in the former per-SoC layout).
mkdir -p "$out"
install -m0644 "$elf" "$out/abl_signed-$soc.elf"
echo "$want  abl_signed-$soc.elf" > "$out/abl_signed-$soc.elf.sha256"
fill() { sed -e "s|@SOC@|$soc|g" -e "s|@PLATFORM@|$platform|g" -e "s|@MODELS@|$models|g" \
             -e "s|@VERSION@|$ABL_VERSION|g" -e "s|@DEVICES@|$devices|g" \
             -e "s|@SHA256@|$want|g"; }
emit_script() {
  printf '%s\n' '#!/system/bin/sh'
  printf '%s' 'eval "$(printf '\''%s\n'\'''
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line//\'/\'\\\'\'}
    printf " '%s'" "$line"
  done
  printf '%s\n' ')"'
}
for s in flash_abl backup_abl restore_abl; do
  cat "$SRC/abl-safety.sh" "$SRC/$s.sh" | fill | emit_script > "$out/$s.sh"
done
fill < "$SRC/README.txt" | sed 's/$/\r/' > "$out/README.txt"
grep -q '@' "$out"/*.sh && die "unfilled placeholder in the scripts"
echo "ROCKNIX ABL $ABL_VERSION for $soc staged in $out"
