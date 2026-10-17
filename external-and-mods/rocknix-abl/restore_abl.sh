
# Restore this device's saved ABL to its original slots.
# The stager inlines abl-safety.sh above this body in the shipped script.
preflight
check_backups
# Snapshot and validate both files before touching either slot.
for slot in a b; do
  cp "$D/abl_$slot.img" "$WORK/abl_$slot.img" || fail "cannot copy backup $slot"
  IFS= read -r expected < "$D/abl_$slot.img.sha256" || fail "cannot read checksum $slot"
  actual=$(sha_of "$WORK/abl_$slot.img") || fail "cannot hash restore image $slot"
  [ "$actual" = "$expected" ] || fail "backup $slot changed during copy"
done
write_slot "$WORK/abl_a.img" "$A"
write_slot "$WORK/abl_b.img" "$B"
finish
echo "Done. Your previous ABL is back on both slots; both readbacks verified."
