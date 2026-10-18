# Pocket EVO build and platform support

## Device kernel

`external-and-mods/kernel-pocketevo` builds Linux 7.2.8 with the
`qcs8550-ayaneo-pocketevo` DTB. Other DTB overrides are rejected. Its kernel
configuration includes the nftables expressions needed by firewalld. Static PIE
BusyBox is accepted for this recipe, and the kernel release suffix is added once.

## Audio and desktop

The EVO sound card uses `AYANEO/PocketEVO/HiFi.conf` for speaker amplifier
setup and UCM routing. The audio helper selects HiFi and waits for its sink.
Other sound cards retain their existing profiles and sink lookup behavior.

On EVO, the `pocket-evo-portal` user generator masks the KDE portal's vendor
Wayland override. The portal inherits the active Game Mode or Plasma environment.

## Build and repack

The October 11 binaries are historical artifacts. After source changes, build
all affected EVO components in new work/output directories: kernel (including
inherited patches and initramfs), Gamescope/WSI, InputPlumber, mangoapp, and the KDE extras bundle.
Build userspace against the read-only baseline rootfs to retain its glibc ABI.
Do not run a builder that writes into the immutable baseline mount. See the
[final validation report](upstream-sync-20261017/FINAL-VALIDATION-BUILD.md) for the
actual commands, versions, logs, component results and unresolved limitations.

The SSD profile is started/stopped with `scripts/pocket-evo-vm.sh`. Inspect its
status, mounts and free space first. Kernel wrapper WORK can point at a fresh
Linux directory; OUT_BASE selects unused output. Gamescope uses STEAMOS_WORK;
InputPlumber uses INPUTPLUMBER_BUILD_SRC/INPUTPLUMBER_OUTPUT and Rust 1.93.1;
mangoapp uses STEAMOS_WORK and an explicit output directory. Preserve existing
cache/build directories. Kernel source, config, patch inputs and userspace
source copies must match the committed product source before repack.

The repacker now requires these explicit container paths:

- `KERNEL_OUTPUT`: newly built `7.2.8-pocketevo-steamos` output.
- `KERNEL_SOURCE`: the source tree used for that compilation.
- `GAMESCOPE_BUILD`: new Meson build directory.
- `INPUTPLUMBER_BUILD`: new binary and SHA256 output directory.
- `MANGOHUD_BUILD`: new mangoapp output directory.
- `KDE_BUILD`: new KDE extras output directory with its stage tree/archive.
- `COMPONENT_MANIFEST`: created by `pocket-evo-component-manifest.py create` and
  verified again before installation.
- `IMAGE_OUTPUT_DIR`: unused artifact directory; existing directories refuse.
- `IMAGE_WORK_PARENT`: defaults to `/artifacts` on SSD, avoiding a second large
  image inside the limited VM disk.

The source checkout must be clean. Run
`docker --context colima-pocket-evo exec` with those environment variables and
`pocket-evo-build bash /src/scripts/repack-pocket-evo-test-image.sh`.
No physical device is opened or written by this pipeline. The private image
copy receives the source runtime delta relative to the embedded baseline
commit, current vendor applications/plugins and newly compiled components.
Every staged runtime file is recorded and checked against installed bytes.
Old `.pyc` beside replaced Python sources is removed. Both `/etc` layers are
updated where present; explicit home preferences are not seeded over.

`verify-pocket-evo-image.py ROOT BOOT HOME KERNEL_OUTPUT GAMESCOPE_BUILD
INPUTPLUMBER_BUILD MANGOHUD_BUILD KDE_BUILD` checks boot payload, modules/firmware,
installed bytes, capabilities, service links, LED preservation and ELF/CLI
loading inside a device-free namespace. FAT and both ext4 partitions must pass
read-only fsck. The repacker preserves baseline SHA256 and partition-table
identity, exports raw/XZ images with SHA256, and checks streaming decompression
against the raw digest. Stop the container and Colima afterward; retain all logs
and artifacts. Successful compilation/repack is not boot or hardware proof.

Gamescope no longer learns a brightness endpoint from arbitrary samples or a
shared state file. Normalized 0..1 input/hotkeys remain available. Nits input
requires an explicit finite `backlight_max_nits` endpoint for the internal
panel/protocol; default 0 refuses uncalibrated nits requests. No panel luminance
calibration is claimed by the build, and the Steam nits slider still requires
real endpoint validation. External-screen events do not adjust the internal
backlight. The five EVO panel mode definitions likewise require device testing.

## Validation

```sh
python3 scripts/tests/test-pocket-evo-isolation.py
python3 scripts/tests/test-pocket-evo-session.py
```

Local tests cover board selection, unchanged behavior on other devices, audio
routing, and kernel recipe isolation. Rebuilt images still require device tests
for speaker output, external-display audio, portal file choosers, and session
switching.
