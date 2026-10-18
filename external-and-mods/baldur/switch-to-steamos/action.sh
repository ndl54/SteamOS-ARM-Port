#!/system/bin/sh
# KernelSU Action and the installer use identical validation and one lock.
set -eu
# The PC needs a checked write/readback result before a separate reboot request.
# KernelSU still invokes the no-argument action, which requests reboot below.
reboot_after=1
case "$#:${1:-}" in
  0:) ;;
  1:--no-reboot) reboot_after=0 ;;
  *) echo 'usage: action.sh [--no-reboot]' >&2; exit 1 ;;
esac
D=/data/adb/steamos-gen5
M=${0%/*}
. "$M/storage.sh"
mkdir "$D/operation.lock" 2>/dev/null || fail "another Gen5 operation is active; inspect a stale lock before retrying"
trap 'rmdir "$D/operation.lock"' EXIT
check_boot
want_android=$(cat "$D/android.sha256")
want_linux=$(cat "$D/linux.img.sha256")
valid_hash "$want_android" && valid_hash "$want_linux" || fail "invalid saved hashes"
[ "$(hash "$b")" = "$want_android" ] || fail "Android backup differs; nothing written"
[ "$(hash "$D/linux.img")" = "$want_linux" ] || fail "staged SteamOS image differs"
size=$(stat -c %s "$D/linux.img")
[ "$size" = "$((sectors * 512))" ] && [ "$(head -c 8 "$D/linux.img")" = 'ANDROID!' ] || fail "invalid SteamOS image size/magic"
backup=$(mktemp -d "$D/boot-backup.XXXXXX")
dd if="$a" of="$backup/boot_a.img" bs=4096 conv=fsync || fail "backup failed"
source_hash=$(hash "$a") && backup_hash=$(hash "$backup/boot_a.img") || fail "cannot hash backup"
[ "$source_hash" = "$backup_hash" ] || fail "backup did not verify"
sync
check_boot
[ "$(hash "$b")" = "$want_android" ] && [ "$(hash "$D/linux.img")" = "$want_linux" ] || fail "inputs changed"
echo "- saved boot_a in $backup; writing SteamOS"
dd if="$D/linux.img" of="$a" bs=4096 conv=fsync || fail "write failed; do not reboot, inspect backup"
blockdev --flushbufs "$a" || fail "flush failed; do not reboot"
[ "$(hash "$a")" = "$want_linux" ] || fail "readback failed; do not reboot, inspect backup"
sync
echo '- boot image verified'
if [ "$reboot_after" = 1 ]; then
  echo '- requesting reboot; boot completion is not verified'
  reboot
fi
