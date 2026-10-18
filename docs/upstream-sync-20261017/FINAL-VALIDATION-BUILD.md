# Final global validation and SSD/Colima build — 2026-10-18

Status: **LOCAL BUILD + OFFLINE IMAGE VALIDATION PASS. Hardware acceptance remains pending.**

## Authority and provenance

The final validation chat alone edits this checkout. It read the external
PROTOCOL.md and state.json without modifying either. Initial clean `main`,
`HEAD=origin/main=git ls-remote origin refs/heads/main`:
`a656b80faf6e4853f07758414ea1dbbcdfec7ca1`. Frozen upstream tip:
`e54dac93afccf76e5fefe998399b6c1b1a23f3a1`. All 109 source commits are ancestors.
No branch, worktree, PR, reset, rewrite, force push, additional chat or subagent.
No physical device access, flashing, installation, deployment or reboot.

[FINAL-QUEUE-AUDIT.json](FINAL-QUEUE-AUDIT.json) preserves every record's checks,
remaining issues and the hash of its review report. It is a historical evidence
inventory, not promotion of previous mocks/text replay to runtime proof.

External artifacts/logs are in:
`/Volumes/Mac Folder/SteamOS-PocketEvo/Steam-OS-ARM-PocketEvo-build/final-validation-20261018`.
Container path: `/artifacts/final-validation-20261018`; new Linux workspace:
`/work/final-20261018`. Existing build/cache directories remain intact. Colima
uses the sibling SSD `colima` home, aarch64 VZ, 6 CPUs, 8 GiB RAM, 60 GiB disk.
Initial host SSD free space ~147 GiB; VM /work free ~24 GiB. Container `/src`
is read-only, `/artifacts` writable, `/work` is the existing Docker volume.

Baseline `/work/image/steamos-arm-port-sm8550-v1.3.2.img` was mounted **ro,noload**
for userspace compilation and inspection. Its embedded older fork manifest is
`b5f4620ecd93d2c84b4eafaa3d2e5b58be028d3e`; it is not pristine Valve rootfs.
Existing October 11 kernel/Gamescope/InputPlumber binaries are not accepted as
current-source output. New kernel work started from a fresh extraction; source
patches applied with fuzz 0. GCC reports `15.3.1 20260722 (Red Hat 15.3.1-1)`;
ROCKNIX checkout is clean at `1ebff24f36501fb6493beb2bf83bf2604536d9aa`.

## Significant finding dispositions

| Records / finding | Disposition and evidence boundary |
| --- | --- |
| 001–008,010–011,014,016–017,023–024,027–028,030–031,045,057–059,064–065,068,071,074,086–087,100,104 | Other-board boot/install, firmware, DT, input, thermal and storage findings remain outside the selected EVO image. They are retained in the audit, not certified by building EVO. Gen5 100 MHz is not proof of SDR50, and reboot exit 2 is unconfirmed. No physical writes performed. |
| 009,012–013,020–021,025 | Updated bootdebug/initramfs installed and byte-verified. Explicit upload remains opt-in; no upload executed. VT/systemd, early mount handover, hotfix RAM budget, kernel-blocked I/O and device capture remain hardware/runtime limitations. |
| 015,022,029,032,035,046 | Gamescope rebuilt from current C++; 74 Meson tests passed. Compile/link cannot establish PipeWire asynchronous teardown, Xwayland pointer lifetime, KMS atomic recovery, external routing/HDR or touch hotplug correctness. |
| 018,037,089,097 | Exact FIT volume daemon gating and EVO separation retained. Mock tests do not establish audio gain, multi-session routing, hold timing, firmware button labels or physical glyph mapping. |
| 019,048,052–053,060–063,066–067,072,105 | Updater cache/settings fixes remain in source; staging ships updater/agent together and records their installed hashes. File-type/symlink races, external writers, recovery/power-loss and upstream feed replacing fork-managed files remain unresolved. No OTA package applied. PyroWave launch code and sysctl files are staged; live codec/box64/Steam library closure and effective sysctl behavior remain unverified; SM8750 staging gap is not an EVO path. |
| 026,034,043,093 | Keyboard-specific fit remains withheld without real Steam/KWin window identity. No global DPI hack or Steam-wide scale substitute. Existing desktop layout/idle migrations retain explicit preferences; rendering/rotation/DPMS and portal behavior require device testing. |
| 036,042,055,083–085,088,090–091 | EVO full ordered kernel stack compiled successfully with Chipone module and packaged output checks. Keep exact board identity, UFS bound, USB before MCU, Wi-Fi restore before scan and Android LED semantics. PM/locking/IRQ/DSI supplier/audio/firmware/storage integrity cannot be certified by compilation. |
| 039 | MangoHud rebuilt at pinned v0.8.4 ref with all seven current patches; installed ELF closure checked. Sensor selection, cached hwmon choice and physical charging/power interpretation remain unverified. |
| 040,044,095 | Dualscreen assets are source changes; EVO is single-panel. Theme tests do not prove QML rendering, contrast of translucent/custom palettes, focus freshness or no flicker. |
| 041,049–051,069,102 Android | Preserve Android persistence/subid/LED paths. Missing APK/framework payload, Lepton API/signatures and live container behavior remain explicit limitations; no Android runtime test. |
| 054 | Classic frame-generation binary is vendored, not newly compiled source. Vendored hash/source identity and installed ELF dependency closure checked; these remain distinct from Vulkan/FEX/Proton/Flatpak compatibility. |
| 056 | Panel mode definitions/DTB arithmetic can be checked. No measured refresh/luminance or physical calibration is inferred; helper locks do not serialize DRM/external writers. |
| 070/103 brightness | **Source repair:** remove inferred persistent top entirely. Nits requests require finite explicit `backlight_max_nits > 1` and valid minimum; reject values above that endpoint before hardware and color-management updates. Default endpoint 0 withholds uncalibrated nits input; normalized input and hotkeys remain. External connector events do not drive internal brightness. This intentionally does not claim a working Steam nits slider without verified panel/protocol configuration. No peak luminance is invented. |
| 075 GPU critical trips | **Source repair:** restore original Linux 115000 mC/0 hysteresis/critical `trip-point2` for all eight SM8650 GPU zones; recreate 40 C fan-labelled nodes under distinct names. Existing passive/hot/cooling maps preserved; no fan calibration/map invented. Compiled full FIT and S2 DTBs retain all 16 GPU critical trips at 115000 mC with zero hysteresis. This is targeted DTS compilation, not a full SM8650 kernel or hardware test. EVO does not include this DTS. |
| 076 haptics | **Partial source repair:** constant upload propagates load error and schedules stop only after success. Remaining global provider lifetime/remove/suspend/gain/timer/calibration races and 7.1 sleep-in-atomic are unresolved. Selected EVO includes the driver but its DT has no compatible haptics provider; final packaged EVO DT verified this exclusion (`final-haptics-dt.json`). This is not a fix/certification for Thor/RP6/Nova. |
| 077–078,108 | Elite gain360 has no established amplifier protection/ACF/thermal/excursion proof. Do not call safe. These are SM8750 boards, not EVO. Removed HDMI UCM does not remove PCM3/kernel DP dependency; USB DACs remain independent. No guessed gain replacement. |
| 079 | Low-battery hook and UPower configuration coherently staged; both root and persistent etc policies checked. RTC ownership, gauge freshness, wake routing and actual shutdown remain hardware limitations; hook interval is not sleep residency. |
| 080–081 | Android reboot and UFS retry preserve authentication/consent/target checks. UFS retry is destructive and is not data recovery. No install/reboot path executed. |
| 082,107,109 | Upstream 1.4 and mutable download badge are not fork release/build/device evidence. Updater feed remains upstream; fork image must be identified by its exact product commit and manifest. |
| 092,096 | Source/revert/current map ancestry retained. Physical DMG/ACE mapping and pinned schema/runtime deck-uhid mismatch not certified. |
| 094 former-system SD | Base 99-steamos-automount.rules inspected: only filesystem usage gets add/remove systemd-run. Base block-device-event waits for udev, not /boot+/home. Formatter accepts a device, unmounts partitions and writes; classification is not consent. Early coldplug remains unresolved; do not claim end-to-end conversion, safe data disposal, format or game registration. |
| 098 S2 | Soft-mixer=true still prevents promised hardware-volume policy; BootSequence84 versus machine cap81 and real UCM/ALSA/WirePlumber initialization require board/runtime evidence. Preserve FIT/headphones and do not invent a safe gain. S2 path not selected by EVO. |
| 099 RemotePad | **Source repair:** backend session token + monotonic sequence; gaps release/invalidate (a missing event may be UP), watchdog releases expired sessions, QML serializes requests with keepalive, UI exit invalidates. Per-owner manual/drag holds, constructor/partial-device cleanup. 12 actual-JS gesture tests, 2 extracted transport tests and actual-class failure probes pass. Actual rootfs Qt lint and an offscreen import smoke also pass; two unqualified XMLHttpRequest lint warnings remain. No rendered UI, uinput/KWin or device proof. |
| 101 Android hash | **Fixed:** separately check sha256sum exit status and strict 64 lowercase hex output; backup hashes assigned and checked before comparison. Failure probes under bash/dash include nonzero producer with plausible output, empty, short and nonhex digests. No Android/block device executed. |
| 102 VDF consumers | **Source repair:** strict UTF-8, required terminators, duplicate rejection, retained uint64 type, NUL rejection; offline-only checked atomic save with unique backup and snapshot conflict detection. Steam ignores advisory locks, so concurrent client start still cannot be excluded. Binary localconfig writer disabled (Steam localconfig is text); select Proton in Steam. Hub offline writer deferred to existing Steam-client API queue, avoiding premature state. Dashboard rejects wrong recents shapes/numeric fields. Tests use temporary files/fake devices only. |

## Build and verification results

The product image is bound to clean source commit `d49757f38bcca0740e45f4fbc02c867b8c566f1c`. Later report-only
commits do not change the embedded product source SHA. All newly compiled binaries
were produced in this run, with no reuse of the old installed kernel/Gamescope/
InputPlumber/mangoapp/KDE outputs. Source/dependency caches were reused, with new
source/build directories and pinned revisions recorded in `component-manifest.json`.

| Gate | Result / evidence |
| --- | --- |
| All 109 queue items | Source ancestry verified; per-item historical evidence retained in `FINAL-QUEUE-AUDIT.json`. Remaining findings above are not promoted to hardware success. |
| Linux 7.2.8 + EVO patches | Fresh full Image/modules/DTBs and Chipone build PASS. Kernel archive SHA256 `12e8d5a973d1ad7c5a5c69882e4022b131ed715db7003fdcd760ddf8c3e51941` matched kernel.org checksum list; ROCKNIX pin above. `kernel-build.log`, `kernel-verification-final.log`. |
| EVO package contracts | Five mode timing calculations (60/90/120/144/165), exact DT identity, side GPIOs/wake/rotation, config, module and firmware checks PASS. These are source/compiled properties, not measured panel behavior. |
| Gamescope | Fresh native rootfs build; 74 Meson tests PASS; both installed paths report 3.16.30-steamos-arm, GCC 15.1.1. Source copy compared to tracked current inputs. `gamescope-build.log`, submodule pins and manifest. |
| InputPlumber | Fresh Rust 1.93.1 release at `ea60d873cca17edd1cb655ede26f557108135252` plus patches 1–4 PASS; CLI reports 0.81.0 and rootfs `ldd -r` PASS. |
| MangoHud | Fresh source `992103e4fb744897826de04ea00a2f71e7018214` plus seven patches PASS; source archive preserved and installed mangoapp hash/ELF checked. |
| KDE | BluezQt 6.14.0, Bluedevil 6.2.5, LibKScreen 6.2.5 and KScreen 6.2.5 built against baseline Qt/KF/Plasma in read-only rootfs. 420-file archive; every staged regular file/symlink and ELF closure checked in image. Tar source hashes recorded. No Bluetooth/display hardware exercised. |
| Source tests | 52 suites final PASS, including 10 final-repair tests, 12 Trackpad and 2 transport JS tests. `tests/final-results.json` retains initial outcomes plus reruns. |
| Focused probes | Extracted actual C++ brightness function assertions PASS; FIT/S2 DT checks PASS; final EVO DT has no affected haptics provider; Qt lint/import smoke PASS. Fixtures, offscreen execution and compile/link are not physical device evidence. |
| Installed image | 955 files compared, plus runtime-staging manifest checks for 197 paths, generated UPower policies and explicit retired path. Kernel payload identical except preserved baseline cmdline; root PARTUUID, module vermagic, capabilities, both etc service links, CLI versions and all selected ELF dependencies PASS. |
| Integrity | Baseline SHA unchanged before/after; partition table identity unchanged; FAT + root/home ext4 read-only fscks PASS; raw SHA, XZ integrity and decompressed SHA equivalence PASS. |
| Environment | This run's private mounts/loop devices released; build container and SSD Colima profile stopped. `vm-stop.log` and final environment evidence. |

Rootfs versions and evidence limits are preserved in `toolchain.txt`: glibc 2.39,
Qt 6.8.0, ALSA library/UCM 1.2.11, PipeWire 1.6.8 and WirePlumber 0.5.18. These
are observed baseline versions; older reports mentioning another ALSA version do
not establish the actual image's runtime. No Steam client, game, compositor,
Bluetooth pairing, input device, suspend/resume, OTA, Android or destructive
storage path was exercised.

## Failures found and repaired during validation

- The initial broad isolation test still used a pre-queue shared-file baseline.
  Its scope now anchors to the fully reviewed starting commit `a656b80`, with
  explicit thermal append handling; the seven isolation tests pass.
- The historical ten-file hash guard dated from `bb37da4`. Three shared files
  gained reviewed tablet/Android/installer changes in the queue. The original
  JSON remains unchanged; the new `pocket-evo-final-preserved-files.json` binds
  all ten files to `a656b80`. LED implementation, services, LED installer, tests
  and documentation still match the historical hashes. No LED code was changed
  in this final validation run. Initial failure and final successful logs remain.
- Initial source-suite run: three patch suites lacked explicit fixture roots,
  framegen used Python 3.9 without `tomllib`, and ABL exceeded the 180-second suite
  limit. Reruns used Python 3.13 and required fixtures. ABL passed all 23 mock
  tests in 197 seconds. Initial five nonzero outcomes remain in `tests/results.json`.
- Repack attempt 1 correctly refused three historical EVO LED source relocations.
  Staging now explicitly maps the two same-destination services to SM8550 and
  removes only the retired module location; unknown deletions still fail closed.
- Attempt 2 was stopped before runtime installation after discovering the
  Gamescope installer still required historical binary hashes. It now requires
  and verifies this run's component manifest, including the selected build paths.
- A full private-image preflight passed before the final fresh-baseline repack.
  Failed/interrupted logs are retained separately; they are not counted as final
  image success. Minor test harness/mount-path errors were corrected and retained
  in the relevant earlier logs. The final manifest uses successful component outputs.

## Reproduction and artifacts

`run-final-repack.sh` in the external log directory records exact component paths,
manifest creation and repack command. Builders run through the existing SSD
Colima/container workflow. Source changes were committed and pushed on `main`
before the successful repack. Native build scopes did not change during subsequent
installer/provenance fixes, and the manifest rechecked all source/output hashes.

Product output directory: `/Volumes/Mac Folder/SteamOS-PocketEvo/Steam-OS-ARM-PocketEvo-build/image-final-20261018-093414-d49757f`.

- Raw image: `steamos-pocketevo-v1.3.2-d49757f-armada-complete-test.img` (19412287488 bytes).
- Compressed image: `steamos-pocketevo-v1.3.2-d49757f-armada-complete-test.img.xz` (6082328900 bytes).
- Raw SHA256: `447896b76cdb6cb7c214ad4ab40afe6ec0ab3880b2bde052849cacd4531e3f3c`.
- XZ SHA256: `25952610b2537d0eebe4f7994d5100513d3c75f29e4f7130fc303419b13c8e56`.
- Baseline SHA256: `cb68d919a9b4f0c0f2e6a2ad5176509560fd8058436826b01bb89646156cb322`.
- `build-manifest.json` is embedded identically in boot and root filesystems.
- `component-manifest.json`, `runtime-staging.json`, `partition-identity.json`,
  `image-verification.json`, `image-build.log`, `IMAGE-SHA256.txt`, `SHA256SUMS`
  accompany the images. Large artifacts remain outside Git.

This is a **test image**, not a hardware-certified release. In particular,
uncalibrated Steam nits requests are deliberately withheld until a verified panel
endpoint is supplied; normalized brightness remains available. Keyboard fit,
former-system-card coldplug, updater races and board-specific haptics/audio/thermal
risks listed above remain open. Building EVO does not certify other boards.
