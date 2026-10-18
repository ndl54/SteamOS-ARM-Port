#!/usr/bin/env bash
# SteamOS ARM on the Lenovo Legion Y700 Gen 5 (TB323FU), from a PC (Linux or
# macOS; Windows: WSL2) with adb. Android stays on the tablet.
#
#   install-gen5.sh [--switch|-switch]
# Optional: ADB=/path/to/adb[.exe], ANDROID_SERIAL=<tablet serial>.
# Exit 2 after --switch means the boot write verified but reboot is unconfirmed.
#
# Before: the tablet rooted without unlocking (LTBox + KernelSU, ZUI
# 18.0.12.104), adb with root allowed for the shell, and the microSD card
# written with steamos-gen5-card.img and back in the tablet.
#
# What it does, each step checked before anything is written:
#   1. checks the tablet, its firmware version and root
#   2. keeps your own Android boot image in boot_b (the way back; once)
#   3. copies the tablet's firmware out of Android (signed for the device,
#      it can't be shipped) and puts it on the card
#   4. builds SteamOS's boot image from your own Android boot image and our
#      kernel (the bootloader only takes one with its stock signature blob)
#   5. stages it for the "Switch to SteamOS" KernelSU module
#   6. with --switch: writes it to boot_a and restarts into SteamOS
# Back to Android: Restart into ZUXOS in Handheld Control, or hold volume up
# + volume down for 10 s.
set -Eeuo pipefail
# Never stop without saying why.
trap 'printf "\nERROR: stopped at line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR
HERE="$(cd "$(dirname "$0")" && pwd)"
KERNEL="$HERE/Image-gen5"
MANIFEST="$HERE/firmware.tsv"
MODULE="$HERE/switch-to-steamos"
WANT_FW=18.0.12.104
D=/data/adb/steamos-gen5
say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
SWITCH=0
[[ $# -le 1 ]] || die "usage: install-gen5.sh [--switch|-switch]"
case "${1:-}" in --switch|-switch) SWITCH=1;; "") ;; *) die "usage: install-gen5.sh [--switch|-switch]";; esac
# Resolve before defining adb(); an explicit executable may contain spaces.
ADB="${ADB:-}"
if [[ -z "$ADB" ]]; then
  ADB="$(command -v adb || command -v adb.exe || true)"
fi
[[ -n "$ADB" ]] && ADB="$(command -v "$ADB")" && [[ -f "$ADB" && -x "$ADB" ]] \
  || die "needs adb (or ADB=/mnt/c/platform-tools/adb.exe from WSL)"
WIN=0
case "$ADB" in *.[eE][xX][eE]) WIN=1;; esac
if ((WIN)); then
  command -v wslpath >/dev/null || die "Windows adb.exe requires wslpath (run inside WSL)"
fi
serial=""
adb() {
  if [[ -n "$serial" ]]; then command "$ADB" -s "$serial" "$@"; else command "$ADB" "$@"; fi
}
host() {
  if ((WIN)); then wslpath -w "$1"; else printf '%s' "$1"; fi
}
# Convert only local sources, never the Android destination. Check conversion
# separately: a failed command substitution inside adb's argv can be masked.
push() {
  local src converted
  local -a sources=()
  while [[ $# -gt 1 ]]; do
    src="$1"; shift
    converted="$(host "$src")" && [[ -n "$converted" ]] || return 1
    sources+=("$converted")
  done
  adb push "${sources[@]}" "$1"
}
su_() { adb shell "su -c '$*'" | tr -d '\r'; }
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
for t in python3 tar; do command -v "$t" >/dev/null || die "needs $t"; done
for f in "$KERNEL" "$MANIFEST" "$MODULE/action.sh" "$HERE/boot-repack.py" "$MODULE/storage.sh"; do [[ -e "$f" ]] || die "missing $f (run from the unpacked release)"; done
# Keep Windows-readable work files beside the release; native hosts keep /tmp.
if ((WIN)); then W="$(mktemp -d "$HERE/.work.XXXXXX")"; else W="$(mktemp -d)"; fi
locked=0
cleanup() {
  local status=$?
  if [[ $locked == 1 ]]; then
    su_ "rmdir $D/operation.lock" || { echo 'Remote lock retained; inspect before retrying' >&2; [[ $status != 0 ]] || status=1; }
  fi
  rm -rf "$W" || { [[ $status != 0 ]] || status=1; }
  exit "$status"
}
trap cleanup EXIT
# Validate all static Windows paths before acquiring a remote lock or writing.
if ((WIN)); then
  for f in "$W" "$MODULE/storage.sh" "$MODULE/action.sh"; do
    converted="$(host "$f")" && [[ -n "$converted" ]] || die "cannot convert Windows host path: $f"
  done
fi

say "1. The tablet"
# get-serialno honors ANDROID_SERIAL; without it adb rejects multiple devices.
# Pin that choice for every later operation, including cleanup and --switch.
serial="$(adb get-serialno | tr -d '\r')" || die "cannot select tablet (use ANDROID_SERIAL for multiple devices)"
[[ -n "$serial" && "$serial" != unknown && "$serial" != *[[:space:]]* ]] || die "invalid adb serial"
state="$(adb get-state 2>/dev/null | tr -d '\r')" && [[ "$state" == device ]] || die "no tablet over adb (USB debugging on)"
model="$(adb shell getprop ro.product.model | tr -d '\r')" || die "cannot read tablet model"
device="$(adb shell getprop ro.product.device | tr -d '\r')" || die "cannot read tablet device"
[[ "$model" == TB323FU || "$device" == baldur ]] || die "this is not a Legion Y700 Gen 5 ($model $device)"
fw="$(adb shell getprop ro.build.display.id | tr -d '\r')"
echo "firmware: $fw"
grep -qF "$WANT_FW" <<<"$fw" || die "only ZUI $WANT_FW is known to work (newer firmware hangs at boot and can't be downgraded)"
root_id="$(su_ id)" && [[ "$root_id" == *"uid=0"* ]] || die "no root for the adb shell (KernelSU: allow Shell)"
su_ "mkdir -p $D && chmod 700 $D && mkdir $D/operation.lock" || die "another Gen5 operation is active"
locked=1
push "$MODULE/storage.sh" /data/local/tmp/sg5-storage.sh >/dev/null
su_ "mv /data/local/tmp/sg5-storage.sh $D/storage.sh && chmod 600 $D/storage.sh"
su_ ". $D/storage.sh; check_boot" || die "boot storage validation failed"
a="$(su_ ". $D/storage.sh; check_boot; echo \"\$a\"" | tail -1)"
b="$(su_ ". $D/storage.sh; check_boot; echo \"\$b\"" | tail -1)"
sa="$(su_ sha256sum $a | cut -d' ' -f1)"; sb="$(su_ sha256sum $b | cut -d' ' -f1)"
[[ "$sa" =~ ^[0-9a-f]{64}$ && "$sb" =~ ^[0-9a-f]{64}$ ]] || die "invalid boot hashes"

say "2. Your Android boot image, kept in boot_b"
prev="$(su_ cat $D/android.sha256 2>/dev/null | cut -d' ' -f1 || true)"
if [[ ${#prev} == 64 ]]; then
  [[ "$sb" == "$prev" ]] || die "boot_b isn't the Android image recorded at the last install: stopping"
  android="$prev"; echo "boot_b already holds it ($android)"
else
  # check_boot requires exact Baldur and a confirmed active Android slot A.
  # Keep the original B too, before replacing it; do not discard an OTA image.
  adb exec-out "su -c 'cat $b'" > "$W/original-boot-b.img"
  [[ "$(sha "$W/original-boot-b.img")" == "$sb" ]] || die "original boot_b backup failed"
  backup="$HERE/gen5-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -m700 "$backup"; cp "$W/original-boot-b.img" "$backup/boot_b.img"
  printf '%s\n' "$sb" > "$backup/boot_b.sha256"
  android="$sa"
  adb exec-out "su -c 'cat $a'" > "$backup/boot_a-android.img"
  [[ "$(sha "$backup/boot_a-android.img")" == "$android" ]] || die "Android PC backup failed"
  python3 "$HERE/boot-repack.py" "$backup/boot_a-android.img" --self-test
  su_ ". $D/storage.sh; check_boot" || die "boot storage changed"
  if [[ "$sb" != "$sa" ]]; then
    echo "boot_a (Android) -> boot_b"
    su_ dd if=$a of=$b bs=4096 conv=fsync >/dev/null 2>&1
    su_ "blockdev --flushbufs $b"
    [[ "$(su_ sha256sum $b | cut -d' ' -f1)" == "$android" ]] || die "boot_b doesn't verify after the copy"
  fi
  su_ "mkdir -p $D && echo $android > $D/android.sha256"
fi
adb exec-out "su -c 'cat $b'" > "$W/stock-boot.img"
[[ "$(sha "$W/stock-boot.img")" == "$android" ]] || die "the copy of the Android boot image on the PC doesn't verify"
backup="$(mktemp -d "$HERE/gen5-android-backup.XXXXXX")"
cp "$W/stock-boot.img" "$backup/boot_a-android.img"
printf '%s\n' "$android" > "$backup/android.sha256"
echo "Android boot image $android; PC backup $backup"

say "3. Firmware from the tablet's Android"
paths=()
while IFS=$'\t' read -r target hash src how; do
  [[ "$target" == \#* || -z "$target" ]] && continue
  if [[ "$how" == squash ]]; then paths+=("$src" "${src%.mdt}.b*"); else paths+=("$src"); fi
done < "$MANIFEST"
adb exec-out "su -c 'cd / && tar -chf - $(printf '%s ' "${paths[@]#/}") 2>/dev/null'" > "$W/fw-src.tar"
mkdir -p "$W/src" "$W/fw"
python3 - "$W/fw-src.tar" "$W/src" <<'EXTRACT'
import pathlib, sys, tarfile
root = pathlib.Path(sys.argv[2])
seen = set()
with tarfile.open(sys.argv[1]) as archive:
    for member in archive:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts:
            raise SystemExit('unsafe firmware source path')
        if member.isdir():
            continue
        if not member.isfile() or not 0 < member.size <= 128 * 1024 * 1024 or str(path) in seen:
            raise SystemExit('invalid firmware source member')
        seen.add(str(path))
        out = root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(archive.extractfile(member).read())
EXTRACT
python3 - "$MANIFEST" "$W/src" "$W/fw" <<'PY'
import hashlib, os, struct, sys
manifest, src, out = sys.argv[1:]
def squash(mdt):
    """Qualcomm split image (X.mdt + X.bNN) back into one ELF, each segment at its p_offset."""
    data = open(mdt, "rb").read()
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[4] not in (1, 2) or data[5] != 1: raise ValueError("invalid little-endian ELF")
    is64 = data[4] == 2
    phoff = struct.unpack_from("<Q" if is64 else "<I", data, 0x20 if is64 else 0x1c)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36 if is64 else 0x2a)
    if phentsize != (56 if is64 else 32) or phnum > 256 or phoff + phnum * phentsize > len(data):
        raise ValueError("invalid program headers")
    img = bytearray(data[:phoff + phnum * phentsize])
    for i in range(phnum):
        ph = phoff + i * phentsize
        off, size = (struct.unpack_from("<Q", data, ph + 8)[0], struct.unpack_from("<Q", data, ph + 0x20)[0]) if is64 \
            else (struct.unpack_from("<I", data, ph + 4)[0], struct.unpack_from("<I", data, ph + 0x10)[0])
        if off + size > 128 * 1024 * 1024: raise ValueError("firmware segment out of bounds")
        if not size: continue
        seg = f"{mdt[:-4]}.b{i:02d}"
        if os.path.exists(seg): chunk = open(seg, "rb").read()
        elif off + size <= len(data): chunk = data[off:off + size]
        else: raise ValueError(f"missing {os.path.basename(seg)}")
        if len(chunk) != size: raise ValueError(f"{os.path.basename(seg)} has the wrong size")
        if len(img) < off + size: img += bytes(off + size - len(img))
        img[off:off + size] = chunk
    return bytes(img)
missing, other = [], 0
for line in open(manifest):
    if line.startswith("#") or not line.strip(): continue
    target, want, srcpath, how = line.rstrip("\n").split("\t")
    p = os.path.join(src, srcpath.lstrip("/"))
    try:
        blob = squash(p) if how == "squash" else open(p, "rb").read()
    except (OSError, ValueError) as e:
        missing.append(f"{target} ({e})"); continue
    if hashlib.sha256(blob).hexdigest() != want: other += 1
    dst = os.path.join(out, target); os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(blob)
print(f"firmware: {sum(len(f) for _, _, f in os.walk(out))} files" + (f", {other} differ from the 18.0.12.104 set" if other else ""))
if missing or other:
    print("missing:\n  " + "\n  ".join(missing)); sys.exit(1)
PY
(cd "$W/fw" && tar -cf "$W/firmware.tar" .)
echo "$android" > "$W/android-boot.sha256"

say "   ... onto the microSD card"
# Validate one physical SD, exact labels, distinct partitions and no existing
# mounts/holders. Never mount a first label match from an unrelated disk.
push "$W/firmware.tar" "$W/android-boot.sha256" /data/local/tmp/ >/dev/null
cat > "$W/card.sh" <<'CARD'
set -eu
. /data/adb/steamos-gen5/storage.sh
# part() validates a unique match and returns explicitly; a later nonmatching
# uevent cannot fail discovery. Do not mask genuine remote/lookup failures.
logs=$(part steamos-gen5-logs) && root=$(part steamos-gen5) || fail 'ambiguous/missing Gen5 card'
[ "$logs" != "$root" ] && [ "$(parent "$logs")" = "$(parent "$root")" ] || fail 'card ancestry differs'
disk=$(parent "$root")
[ "$(cat "$disk/device/type")" = SD ] || fail 'not an SD card'
[ "$(cat /sys/class/block/${logs##*/}/partition)" = 1 ] && [ "$(cat /sys/class/block/${root##*/}/partition)" = 2 ] || fail 'wrong card layout'
unused "$logs"; unused "$root"
m=$(mktemp -d /data/local/tmp/sg5.XXXXXX)
mounted=0
cleanup_card() {
  status=$?
  trap - EXIT
  if [ "$status" != 0 ]; then echo "card stage failed ($status): $card_step" >&2; fi
  if [ "$mounted" = 1 ]; then
    umount "$m" || {
      echo "mount retained: $m" >&2
      [ "$status" != 0 ] || status=1
      exit "$status"
    }
  fi
  rmdir "$m" || { echo "card work directory retained: $m" >&2; [ "$status" != 0 ] || status=1; }
  exit "$status"
}
card_step=mount
trap cleanup_card EXIT
# Android sh has no portable pipefail/ERR trap. Check sha256sum separately:
# two failed/empty hashes must never compare equal and publish unverified data.
card_hash() {
  digest=$(sha256sum "$1") || return 1
  digest=${digest%% *}
  valid_hash "$digest" || return 1
  printf '%s\n' "$digest"
}
verify_card_copy() {
  expected=$(card_hash "$1") && actual=$(card_hash "$2") || fail "cannot hash card copy: $2"
  [ "$expected" = "$actual" ] || fail "card readback failed: $2"
}
mount -t vfat -o nosuid,nodev,noexec "$logs" "$m"
mounted=1
card_step=copy
cp /data/local/tmp/firmware.tar "$m/firmware.tar.new"
cp /data/local/tmp/android-boot.sha256 "$m/android-boot.sha256.new"
card_step=readback
verify_card_copy /data/local/tmp/firmware.tar "$m/firmware.tar.new"
verify_card_copy /data/local/tmp/android-boot.sha256 "$m/android-boot.sha256.new"
card_step=publish
mv "$m/firmware.tar.new" "$m/firmware.tar"
mv "$m/android-boot.sha256.new" "$m/android-boot.sha256"
card_step=sync
sync
CARD
push "$W/card.sh" /data/local/tmp/sg5-card.sh >/dev/null
su_ "sh /data/local/tmp/sg5-card.sh" || die "could not stage firmware on the card"

echo "firmware and the Android image hash are on the card"

say "4. SteamOS's boot image"
python3 "$HERE/boot-repack.py" "$W/stock-boot.img" "$KERNEL" "$W/linux.img" | tail -2
linux="$(sha "$W/linux.img")"
echo "SteamOS boot image $linux"

say "5. Switch to SteamOS (KernelSU module)"
push "$W/linux.img" /data/local/tmp/steamos-gen5.img >/dev/null
su_ "mkdir -p $D && mv /data/local/tmp/steamos-gen5.img $D/linux.img && echo $linux > $D/linux.img.sha256 && chmod 600 $D/linux.img"
[[ "$(su_ sha256sum $D/linux.img | cut -d' ' -f1)" == "$linux" ]] || die "the staged image doesn't verify on the tablet"
rm -rf "$W/module"; cp -r "$MODULE" "$W/module"; echo "$android" > "$W/module/android.sha256"
(cd "$W/module" && python3 -c 'import shutil, sys; shutil.make_archive(sys.argv[1], "zip", ".")' "$W/switch-to-steamos")
push "$W/switch-to-steamos.zip" /data/local/tmp/ >/dev/null
su_ "cp /data/local/tmp/switch-to-steamos.zip $D/ && /data/adb/ksud module install /data/local/tmp/switch-to-steamos.zip >/dev/null 2>&1" \
  || echo "note: install switch-to-steamos.zip from $D in the KernelSU app"
push "$MODULE/action.sh" /data/local/tmp/sg5-action.sh >/dev/null
su_ "mv /data/local/tmp/sg5-action.sh $D/action.sh && chmod 755 $D/action.sh"
echo "staged. In Android: KernelSU > Modules > Switch to SteamOS > Action"

su_ "rmdir $D/operation.lock"; locked=0
if [[ $SWITCH == 1 ]]; then
  say "6. Preparing the switch to SteamOS"
  # Never suppress an Action error: all target/backup/write/readback checks and
  # lock cleanup must return successfully while the device is still connected.
  su_ "sh $D/action.sh --no-reboot" || die "switch preparation failed; no reboot requested, inspect the tablet and backups"
  say "Boot image verified; requesting reboot"
  # A transport loss here cannot tell us whether reboot was accepted. Keep its
  # output and report uncertainty, without labelling the verified write failed
  # or treating any nonzero result (including permission errors) as success.
  # Suppress inherited ERR diagnostics only for this separately handled request.
  if (trap - ERR; command "$ADB" -s "$serial" shell "su -c 'reboot'") > "$W/reboot.log" 2>&1; then
    tr -d '\r' < "$W/reboot.log"
    say "Reboot command returned successfully; SteamOS boot is not verified"
  else
    reboot_status=$?
    tr -d '\r' < "$W/reboot.log" >&2
    printf '\nReboot request unconfirmed (ADB status %s). The tablet may be restarting. Check it before retrying; the boot image was verified.\n' "$reboot_status" >&2
    exit 2
  fi
else
  say "Done: staged for KernelSU Action"
fi
