#!/system/bin/sh
# Shared Android-side checks. Sourced only; every caller holds the same lock.
fail() { echo "! $*" >&2; exit 1; }
hash() {
  digest=$(sha256sum "$1") || return 1
  digest=${digest%% *}
  valid_hash "$digest" || return 1
  printf '%s\n' "$digest"
}
valid_hash() { [ "${#1}" = 64 ] && case "$1" in *[!0-9a-f]*) return 1;; esac; }
part() {
  n=0; dev=""
  for u in /sys/class/block/*/uevent; do
    grep -qx "PARTNAME=$1" "$u" || continue
    n=$((n + 1)); dev=$(sed -n 's/^DEVNAME=//p' "$u")
  done
  [ "$n" = 1 ] && [ -b "/dev/block/$dev" ] || return 1
  echo "/dev/block/$dev"
}
parent() { dirname "$(readlink -f /sys/class/block/${1##*/})"; }
unused() {
  node=${1##*/}; sys=/sys/class/block/$node
  [ -b "$1" ] && [ "$(cat "$sys/ro")" = 0 ] || fail "invalid/read-only device"
  id=$(cat "$sys/dev")
  # findmnt is not required in Android. mountinfo matches aliases by major:minor.
  awk -v id="$id" '$3 == id { found=1 } END { exit !found }' /proc/self/mountinfo && fail "target is mounted"
  for h in "$sys"/holders/*; do [ ! -e "$h" ] || fail "target has holders"; done
  # Android swap is conservatively refused; loops are never detached.
  [ "$(wc -l < /proc/swaps)" -le 1 ] || fail "disable swap first"
  for f in /sys/class/block/loop*/loop/backing_file; do
    [ -e "$f" ] || continue
    back=$(cat "$f")
    [ -e "$back" ] || fail "unresolved loop backing path"
    [ "$(readlink -f "$back")" != "$(readlink -f "$1")" ] || fail "target backs a loop"
  done
}
check_boot() {
  [ "$(id -u)" = 0 ] || fail "root required"
  compat=/sys/firmware/devicetree/base/compatible
  [ -r "$compat" ] || compat=/proc/device-tree/compatible
  tr '\0' '\n' < "$compat" | grep -qx 'lenovo,baldur' || fail "not Lenovo Baldur"
  [ "$(getprop ro.boot.slot_suffix)" = _a ] || fail "requires Android started from slot A"
  a=$(part boot_a) && b=$(part boot_b) || fail "boot partitions missing or ambiguous"
  [ "$a" != "$b" ] && [ "$(parent "$a")" = "$(parent "$b")" ] || fail "boot ancestry differs"
  p=$(parent "$a"); ufs=0
  while [ "$p" != / ]; do
    driver=$(basename "$(readlink -f "$p/driver")")
    case "$driver" in ufshcd-qcom|ufshcd) ufs=1;; esac
    p=$(dirname "$p")
  done
  [ "$ufs" = 1 ] || fail "boot partitions are not UFS"
  sectors=$(cat /sys/class/block/${a##*/}/size)
  [ "$sectors" -gt 0 ] && [ "$sectors" = "$(cat /sys/class/block/${b##*/}/size)" ] || fail "boot sizes differ"
  [ "$(head -c 8 "$a")" = 'ANDROID!' ] || fail "boot_a magic missing"
  unused "$a"; unused "$b"
}
