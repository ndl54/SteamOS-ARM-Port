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

The prepared ARM64 container requires the base image, `/work/image-path`,
`/work/original-KERNEL`, `/work/rocknix`, `/work/frame-fw`, and
`/artifacts/base-os-release.txt`.

```sh
bash scripts/pocket-evo-vm.sh start
docker --context colima-pocket-evo exec pocket-evo-build bash /src/scripts/build-pocket-evo-kernel.sh
docker --context colima-pocket-evo exec pocket-evo-build bash /src/scripts/repack-pocket-evo-test-image.sh
bash scripts/pocket-evo-vm.sh stop
```

Kernel output is `/work/kernel-pocketevo/output/current`; repacking requires
`7.2.8-pocketevo-steamos`. The repack installs the kernel, modules and runtime
files, checks the image filesystems, and records source and file hashes.
Compressed and ready-to-flash images are written to
`Steam-OS-ARM-PocketEvo-build/output`. This image is for Pocket EVO only.

## Validation

```sh
python3 scripts/tests/test-pocket-evo-isolation.py
python3 scripts/tests/test-pocket-evo-session.py
```

Local tests cover board selection, unchanged behavior on other devices, audio
routing, and kernel recipe isolation. Rebuilt images still require device tests
for speaker output, external-display audio, portal file choosers, and session
switching.
