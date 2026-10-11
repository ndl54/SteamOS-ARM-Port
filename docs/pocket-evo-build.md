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

The prepared ARM64 container reuses the existing base image from
`/work/image-path`, verified kernel output and verified Gamescope build. No
component recompilation is required. The source checkout must be clean.

```sh
bash scripts/pocket-evo-vm.sh start
docker --context colima-pocket-evo exec \
  -e KERNEL_OUTPUT=/artifacts/audit-build-20261011/kernel/current \
  -e GAMESCOPE_BUILD=/artifacts/gamescope-final-20261011/gamescope-3.16.30-pocket-evo-aarch64/build \
  -e IMAGE_OUTPUT_DIR=/artifacts/image-final-20261011 \
  pocket-evo-build bash /src/scripts/repack-pocket-evo-test-image.sh
bash scripts/pocket-evo-vm.sh stop
```

Choose an unused IMAGE_OUTPUT_DIR for each run; existing directories are refused.
The repack creates a private image copy, preserves the base image SHA256 and boot
partition identity, and installs the verified kernel/modules/firmware,
Gamescope+WSI+profiles, patched InputPlumber, current input mappings and EVO
platform/audio/sleep/LED files. It uses the existing installers and retains
LED/RGB source bytes. Gamescope file capabilities are restored after copying.

`scripts/verify-pocket-evo-image.py ROOT BOOT HOME KERNEL_OUTPUT GAMESCOPE_BUILD`
checks boot payload, installed bytes, capability values, service links in both
/etc layers, LED preservation and CLI/library loading inside the image without
launching a compositor. FAT and both ext4 partitions must pass read-only fsck.
Both `.img` and `.img.xz` are exported with SHA256 manifests; streaming
decompression must match the raw image hash. A build manifest is stored inside
the image and next to the output. No file is written to a physical device.

The current image output directory is under the sibling
`Steam-OS-ARM-PocketEvo-build/image-final-20261011`. This image is for Pocket EVO
only. It contains five panel mode definitions; actual rates/HDR and lifecycle
still require hardware testing.

## Validation

```sh
python3 scripts/tests/test-pocket-evo-isolation.py
python3 scripts/tests/test-pocket-evo-session.py
```

Local tests cover board selection, unchanged behavior on other devices, audio
routing, and kernel recipe isolation. Rebuilt images still require device tests
for speaker output, external-display audio, portal file choosers, and session
switching.
