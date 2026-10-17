
# Save the ABL on this device (ROCKNIX ABL @VERSION@, @SOC@).
# The stager inlines abl-safety.sh above this body in the shipped script.
preflight
backup
finish
echo "Saved/verified abl_a.img, abl_b.img and both .sha256 files in $D. Copy all four to a PC and keep them."
