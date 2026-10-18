# Final global validation and SSD/Colima build — 2026-10-18

Status: **IN PROGRESS — no image/build/hardware success claimed yet.**

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

Baseline `/work/image/steamos-arm-port-sm8550-v1.3.2.img` is mounted **ro,noload**
for userspace compilation and inspection. Its embedded older fork manifest is
`b5f4620ecd93d2c84b4eafaa3d2e5b58be028d3e`; it is not pristine Valve rootfs.
Existing October 11 kernel/Gamescope/InputPlumber binaries are not accepted as
current-source output. New kernel work starts from a fresh extraction; source
patches apply with fuzz 0. GCC reports `15.3.1 20260722 (Red Hat 15.3.1-1)`;
ROCKNIX checkout is clean at `1ebff24f36501fb6493beb2bf83bf2604536d9aa`.

## Significant finding dispositions

| Records / finding | Disposition and evidence boundary |
| --- | --- |
| 001–008,010–011,014,016–017,023–024,027–028,030–031,045,057–059,064–065,068,071,074,086–087,100,104 | Other-board boot/install, firmware, DT, input, thermal and storage findings remain outside the selected EVO image. They are retained in the audit, not certified by building EVO. Gen5 100 MHz is not proof of SDR50, and reboot exit 2 is unconfirmed. No physical writes performed. |
| 009,012–013,020–021,025 | Updated bootdebug/initramfs must be installed and byte-verified. Explicit upload remains opt-in; no upload executed. VT/systemd, early mount handover, hotfix RAM budget, kernel-blocked I/O and device capture remain hardware/runtime limitations. |
| 015,022,029,032,035,046 | Gamescope is being rebuilt from current C++. Compile/link cannot establish PipeWire asynchronous teardown, Xwayland pointer lifetime, KMS atomic recovery, external routing/HDR or touch hotplug correctness. |
| 018,037,089,097 | Exact FIT volume daemon gating and EVO separation retained. Mock tests do not establish audio gain, multi-session routing, hold timing, firmware button labels or physical glyph mapping. |
| 019,048,052–053,060–063,066–067,072,105 | Updater cache/settings fixes remain in source; staging must ship updater/agent together. File-type/symlink races, external writers, recovery/power-loss and upstream feed replacing fork-managed files remain unresolved. No OTA package applied. PyroWave codec/box64/library and effective sysctl behavior require image checks; SM8750 staging gap is not an EVO path. |
| 026,034,043,093 | Keyboard-specific fit remains withheld without real Steam/KWin window identity. No global DPI hack or Steam-wide scale substitute. Existing desktop layout/idle migrations retain explicit preferences; rendering/rotation/DPMS and portal behavior require device testing. |
| 036,042,055,083–085,088,090–091 | EVO full ordered kernel stack is being compiled. Keep exact board identity, UFS bound, USB before MCU, Wi-Fi restore before scan and Android LED semantics. PM/locking/IRQ/DSI supplier/audio/firmware/storage integrity cannot be certified by compilation. |
| 039 | MangoHud patch changes require rebuilt mangoapp; prior text application alone is not sufficient. Sensor selection, cached hwmon choice and physical charging/power interpretation remain unverified. |
| 040,044,095 | Dualscreen assets are source changes; EVO is single-panel. Theme tests do not prove QML rendering, contrast of translucent/custom palettes, focus freshness or no flicker. |
| 041,049–051,069,102 Android | Preserve Android persistence/subid/LED paths. Missing APK/framework payload, Lepton API/signatures and live container behavior remain explicit limitations; no Android runtime test. |
| 054 | Classic frame-generation binary is vendored, not newly compiled source. Hash/source identity and ELF dependency closure must be distinguished from Vulkan/FEX/Proton/Flatpak compatibility. |
| 056 | Panel mode definitions/DTB arithmetic can be checked. No measured refresh/luminance or physical calibration is inferred; helper locks do not serialize DRM/external writers. |
| 070/103 brightness | **Source repair:** remove inferred persistent top entirely. Nits requests require finite explicit `backlight_max_nits > 1` and valid minimum; reject values above that endpoint before hardware and color-management updates. Default endpoint 0 withholds uncalibrated nits input; normalized input and hotkeys remain. External connector events do not drive internal brightness. This intentionally does not claim a working Steam nits slider without verified panel/protocol configuration. No peak luminance is invented. |
| 075 GPU critical trips | **Source repair:** restore original Linux 115000 mC/0 hysteresis/critical `trip-point2` for all eight SM8650 GPU zones; recreate 40 C fan-labelled nodes under distinct names. Existing passive/hot/cooling maps preserved; no fan calibration/map invented. Requires DT compilation check. EVO does not include this DTS. |
| 076 haptics | **Partial source repair:** constant upload propagates load error and schedules stop only after success. Remaining global provider lifetime/remove/suspend/gain/timer/calibration races and 7.1 sleep-in-atomic are unresolved. Selected EVO includes the driver but its DT has no compatible haptics provider; compiled DT must verify this exclusion. This is not a fix/certification for Thor/RP6/Nova. |
| 077–078,108 | Elite gain360 has no established amplifier protection/ACF/thermal/excursion proof. Do not call safe. These are SM8750 boards, not EVO. Removed HDMI UCM does not remove PCM3/kernel DP dependency; USB DACs remain independent. No guessed gain replacement. |
| 079 | Low-battery hook and UPower configuration must be coherently staged. RTC ownership, gauge freshness, wake routing and actual shutdown remain hardware limitations; hook interval is not sleep residency. |
| 080–081 | Android reboot and UFS retry preserve authentication/consent/target checks. UFS retry is destructive and is not data recovery. No install/reboot path executed. |
| 082,107,109 | Upstream 1.4 and mutable download badge are not fork release/build/device evidence. Updater feed remains upstream; fork image must be identified by its exact product commit and manifest. |
| 092,096 | Source/revert/current map ancestry retained. Physical DMG/ACE mapping and pinned schema/runtime deck-uhid mismatch not certified. |
| 094 former-system SD | Base 99-steamos-automount.rules inspected: only filesystem usage gets add/remove systemd-run. Base block-device-event waits for udev, not /boot+/home. Formatter accepts a device, unmounts partitions and writes; classification is not consent. Early coldplug remains unresolved; do not claim end-to-end conversion, safe data disposal, format or game registration. |
| 098 S2 | Soft-mixer=true still prevents promised hardware-volume policy; BootSequence84 versus machine cap81 and real UCM/ALSA/WirePlumber initialization require board/runtime evidence. Preserve FIT/headphones and do not invent a safe gain. S2 path not selected by EVO. |
| 099 RemotePad | **Source repair:** backend session token + monotonic sequence; gaps release/invalidate (a missing event may be UP), watchdog releases expired sessions, QML serializes requests with keepalive, UI exit invalidates. Per-owner manual/drag holds, constructor/partial-device cleanup. Existing 12 actual-JS gesture tests and new actual-class failure probes pass. No uinput/Qt/KWin/device proof. |
| 101 Android hash | **Fixed:** separately check sha256sum exit status and strict 64 lowercase hex output; backup hashes assigned and checked before comparison. Failure probes under bash/dash include nonzero producer with plausible output, empty, short and nonhex digests. No Android/block device executed. |
| 102 VDF consumers | **Source repair:** strict UTF-8, required terminators, duplicate rejection, retained uint64 type, NUL rejection; offline-only checked atomic save with unique backup and snapshot conflict detection. Steam ignores advisory locks, so concurrent client start still cannot be excluded. Binary localconfig writer disabled (Steam localconfig is text); select Proton in Steam. Hub offline writer deferred to existing Steam-client API queue, avoiding premature state. Dashboard rejects wrong recents shapes/numeric fields. Tests use temporary files/fake devices only. |

## Commands and current results

- `bash scripts/pocket-evo-vm.sh status/start`; output in `vm-start.log`.
- Fresh kernel `--prepare-only`: `kernel-prepare.log`, PASS full EVO patch chain.
- Fresh kernel build: `kernel-build.log`, ongoing; not yet a success claim.
- Userspace runner: external `build-userspace.sh`, `gamescope-build.log`,
  `inputplumber-build.log`, per-component exit files. Baseline stays read-only.
- `python3 -B scripts/tests/test-final-validation.py`: 10 tests PASS, including
  actual VDF implementations, actual extracted RemoteInput class, checked shell
  hash failures. `final-repairs-tests.log`. Initial test harness mistakes are
  corrected; no hardware behavior inferred.
- `node scripts/tests/test-bottom-screen-trackpad.cjs`: 12 PASS (`trackpad.log`).
- EVO isolation/session logs: `isolation.log`, `session.log`.
- `git diff --check` excludes patch context whitespace; added C payload is
  reviewed separately. Final clean-source/provenance checks remain pending.

## Completion gates still pending

Actual successful kernel/Gamescope/InputPlumber/mangoapp compilations; compiled
DTB/config/module/firmware checks; updated runtime staging and component manifests;
image installed-byte/capability/service/ELF checks; baseline/partition identity;
FAT and two ext4 read-only fscks; raw and XZ hashes plus decompression equivalence;
container/Colima shutdown; final commit/push and independent SHA equality.
