#!/system/bin/sh
# Inlined into each shipped script: no runtime sourcing, $0 or caller PATH.
PATH=/system/bin:/system/xbin
export PATH
D=/sdcard/rocknix_abl
A=/dev/block/by-name/abl_a
B=/dev/block/by-name/abl_b
WRITING=0
WORK=

fail() {
  echo "STOPPED: $*" >&2
  if [ "$WRITING" = 1 ]; then
    echo "An ABL slot may have changed. Do NOT restart; keep the backups and recover with restore_abl.sh." >&2
  else
    echo "No ABL partition was written by this run." >&2
  fi
  exit 1
}

cleanup() {
  status=$?
  trap - 0
  if [ -n "$WORK" ] && ! rm -rf "$WORK"; then
    echo "Could not remove temporary files: $WORK" >&2
    status=1
  fi
  exit "$status"
}
trap cleanup 0
trap 'fail "interrupted"' 1 2 15

finish() {
  rm -rf "$WORK" || fail "cannot remove temporary files: $WORK"
  WORK=
}

positive_size() {
  case $1 in ''|*[!0-9]*|0) return 1 ;; esac
}
file_size() {
  count=$(wc -c < "$1") || return 1
  printf '%s' "$count" | tr -d '[:space:]'
}
sha_of() {
  hash=$(sha256sum "$1") || return 1
  hash=${hash%% *}
  case $hash in ''|*[!0-9a-f]*) return 1 ;; esac
  [ "${#hash}" = 64 ] || return 1
  printf '%s\n' "$hash"
}

preflight() {
  for tool in getprop blockdev readlink sha256sum dd head wc tr mktemp cp mv rm sync; do
    command -v "$tool" >/dev/null 2>&1 || fail "Android tool missing: $tool"
  done
  # A bare root-tool shell may have no PATH or a meaningless $0. Use the
  # Android system PATH, and test access instead of relying on an id wrapper.
  model=$(getprop ro.soc.model) || fail "cannot read Android SoC"
  platform=$(getprop ro.board.platform) || fail "cannot read Android platform"
  matched=0
  for m in @MODELS@; do [ "$model" = "$m" ] && matched=1; done
  [ -n "$platform" ] && [ "$platform" = "@PLATFORM@" ] && matched=1
  [ "$matched" = 1 ] || fail "this folder is for @SOC@; Android reports '$model' / '$platform'"
  [ -d "$D" ] && [ -w "$D" ] || fail "copy the folder to $D first"
  for slot in a b; do
    for old in "$D/@SOC@/abl_$slot.img" "$D/@SOC@/abl_$slot.img.sha256"; do
      [ ! -e "$old" ] && [ ! -L "$old" ] || fail "legacy backup in $D/@SOC@: keep it for independent verification/recovery before using the flat folder"
    done
  done
  for part in "$A" "$B"; do
    [ -b "$part" ] && [ -r "$part" ] && [ -w "$part" ] || fail "ABL block partition unavailable: $part (run as root)"
  done
  real_a=$(readlink -f "$A") || fail "cannot resolve abl_a"
  real_b=$(readlink -f "$B") || fail "cannot resolve abl_b"
  [ -n "$real_a" ] && [ -n "$real_b" ] && [ "$real_a" != "$real_b" ] || fail "ABL slots must be distinct"
  size_a=$(blockdev --getsize64 "$A") || fail "cannot size abl_a"
  size_b=$(blockdev --getsize64 "$B") || fail "cannot size abl_b"
  positive_size "$size_a" && positive_size "$size_b" || fail "invalid ABL partition size"
  WORK=$(mktemp -d "$D/.abl-work.XXXXXX") || fail "cannot create temporary directory"
}

check_backups() {
  for slot in a b; do
    img=$D/abl_$slot.img
    [ -f "$img" ] && [ -f "$img.sha256" ] || fail "incomplete or legacy backup: keep all existing files; verified .img and .img.sha256 pairs are required"
    size=$(file_size "$img") || fail "cannot size backup $slot"
    case $slot in a) capacity=$size_a ;; b) capacity=$size_b ;; esac
    [ "$size" = "$capacity" ] || fail "backup $slot is not a full partition image"
    IFS= read -r expected < "$img.sha256" || fail "cannot read backup checksum $slot"
    actual=$(sha_of "$img") || fail "cannot hash backup $slot"
    [ "$actual" = "$expected" ] || fail "backup $slot checksum mismatch"
  done
}

backup() {
  # Never overwrite even one old/partial backup. A partial pair needs human
  # recovery, not a new backup of a possibly already-flashed partition.
  for slot in a b; do
    for old in "$D/abl_$slot.img" "$D/abl_$slot.img.sha256"; do
      if [ -e "$old" ] || [ -L "$old" ]; then
        check_backups
        echo "Keeping the existing verified backup pair."
        return 0
      fi
    done
  done
  for slot in a b; do
    case $slot in a) part=$A; capacity=$size_a ;; b) part=$B; capacity=$size_b ;; esac
    img=$WORK/abl_$slot.img
    dd if="$part" of="$img" bs=4096 || fail "backup read failed for $slot"
    size=$(file_size "$img") || fail "cannot size backup $slot"
    [ "$size" = "$capacity" ] || fail "short backup for $slot"
    actual=$(sha_of "$img") || fail "cannot hash backup $slot"
    original=$(sha_of "$part") || fail "cannot hash partition $slot"
    [ "$actual" = "$original" ] || fail "backup verification failed for $slot"
    printf '%s\n' "$actual" > "$img.sha256" || fail "cannot save backup checksum"
  done
  for slot in a b; do
    mv "$WORK/abl_$slot.img" "$D/abl_$slot.img" || fail "cannot save backup $slot"
    mv "$WORK/abl_$slot.img.sha256" "$D/abl_$slot.img.sha256" || fail "cannot save checksum $slot"
  done
  sync || fail "backup sync failed"
  check_backups
}

write_slot() {
  image=$1
  part=$2
  size=$(file_size "$image") || fail "cannot size write image"
  expected=$(sha_of "$image") || fail "cannot hash write image"
  WRITING=1
  dd if="$image" of="$part" bs=4096 conv=fsync || fail "write failed: $part"
  sync || fail "sync failed: $part"
  head -c "$size" "$part" > "$WORK/readback" || fail "readback failed: $part"
  actual=$(sha_of "$WORK/readback") || fail "cannot hash readback: $part"
  [ "$actual" = "$expected" ] || fail "readback mismatch: $part"
}
