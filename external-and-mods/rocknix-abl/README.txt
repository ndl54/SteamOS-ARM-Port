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

1. Keep the whole rocknix_abl folder on the microSD card's BOOT drive,
   visible to Android as /storage/<card>/rocknix_abl. Alternatively use
   /sdcard/rocknix_abl. Run the generated flash_abl.sh as root. The scripts
   discover these locations independently of the working directory.
   Multiple distinct folders stop the operation; never guess which copy
   holds your original backups or discard backups just to bypass this stop.
2. The script first saves your current ABL as abl_a.img
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
Backups in former SMxxxx subfolders also stop the scripts; retain those
folders for verification/recovery instead of hiding or deleting them.

The generated scripts contain one complete action on one physical shell
line for root tools that run lines separately. Keep that line intact; do
not run the repository's partial templates directly. A symlink alias of
one folder is accepted if it resolves to the same path; image/backup files
must be regular files, not symlinks. Android mount aliases that resolve to
different paths are conservatively treated as distinct folders.

SoC/platform checks do not identify an exact board or physical device.
A filename or matching hash does not prove boot compatibility, authenticity
of a backup, or ownership by this device. Use only the listed hardware and
this device's own independently retained backups.

On a write/readback error, a slot may already have changed. Do NOT restart;
keep the backups and recover using restore_abl.sh. Do not run scripts in
parallel. No script changes the active slot or reboots automatically.

Android keeps working with ROCKNIX ABL: choose Android in the ABL menu.
