
# Put ROCKNIX ABL @VERSION@ (@SOC@) on both ABL slots.
# The stager inlines abl-safety.sh above this body in the shipped script.
preflight
cp "$D/abl_signed-@SOC@.elf" "$WORK/new.elf" || fail "missing or unreadable ABL image"
actual=$(sha_of "$WORK/new.elf") || fail "cannot hash ABL image"
[ "$actual" = "@SHA256@" ] || fail "ABL image differs from the pinned release; copy the folder again"
size=$(file_size "$WORK/new.elf") || fail "cannot size ABL image"
positive_size "$size" && [ "$size" -le "$size_a" ] && [ "$size" -le "$size_b" ] || fail "ABL image does not fit both slots"
backup
write_slot "$WORK/new.elf" "$A"
write_slot "$WORK/new.elf" "$B"
finish
echo "Done. Both slots verified. Copy abl_a.img, abl_b.img and both .sha256 files to a PC."
echo "Restart holding Volume Down: set your device model, choose Linux, Start."
