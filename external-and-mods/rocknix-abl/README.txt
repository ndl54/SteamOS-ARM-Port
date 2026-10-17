ROCKNIX ABL @VERSION@ for @SOC@ (@DEVICES@)

The bootloader menu that lets this device start SteamOS from the microSD
card or internal storage, and still start Android. From the ROCKNIX project
(https://github.com/ROCKNIX/abl), GPL-2.0, (c) ROCKNIX contributors. Only
needed once; skip this if the ABL menu already shows ROCKNIX ABL @VERSION@
or newer.

You need Android's "run script as root" option (in the device's settings).
Use only this chip's folder on the supported devices listed above. Scripts
check Android's SoC/platform and both ABL partitions before writing. If the
root tool cannot expose those checks or required Android tools, they stop.

1. In Android, copy this whole rocknix_abl folder from the microSD card's
   BOOT drive to the top of Android's internal storage, so it ends up as
   /sdcard/rocknix_abl (the scripts look for it there).
2. Run flash_abl.sh as root. It first saves your current ABL as abl_a.img
   and abl_b.img with .sha256 files in the same folder. It verifies the
   pinned image and full backups, then writes and reads back each slot.
   Existing backups are kept. Copy both .img and both .sha256 files to a
   PC and keep them; they belong to this device only.
3. Only after a successful "Done", restart holding Volume Down. In the
   menu (Volume to move, Power to select): set your device model, choose
   Linux as the boot mode, Start.

To go back to the ABL you had: run restore_abl.sh as root from the same
folder. backup_abl.sh only takes the backup, without flashing anything.
Both slots are checked before restore. Partial backups, wrong sizes or bad
checksums stop the scripts before any partition write. Keep incomplete or
legacy backups without .sha256 files: do not delete them or create new
checksums to bypass a failure. They require independent verification and
recovery; these scripts will not silently trust or overwrite them.
Backups in the former @SOC@ subfolder also stop the scripts; retain that
folder for verification/recovery instead of hiding or deleting it.

On a write/readback error, a slot may already have changed. Do NOT restart;
keep the backups and recover using restore_abl.sh. Do not run scripts in
parallel. No script changes the active slot or reboots automatically.

Android keeps working with ROCKNIX ABL: choose Android in the ABL menu.
