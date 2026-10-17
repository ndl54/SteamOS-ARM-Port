# 039 — CPU thermal fallback and charging diagnostics

## Scope and ancestry

- Source: `beffbe832e6f53a3a1e7489feae7f35899e73fb2` — `fix(overlay): CPU temperature on the 8 Elite, charging state in debug logs`.
- Sole source parent: `dd36e446e43252bbf8795fcf110b9010f07ffb16` (previously integrated).
- Starting main: `bb9f8819866985331d1ce2fc3458d11e4d19e129`.
- Before mutation, verified clean `main`, absent MERGE_HEAD, and HEAD = origin/main = independent `git ls-remote origin refs/heads/main` = expected start. `git rev-list HEAD..SOURCE` returned only this source. Repeated these gates immediately before merging.
- Used `git merge --no-ff --no-commit SOURCE`; automatic merge succeeded without text conflicts. Retained upstream ancestry. No other queue source, branch, worktree, PR or chat was created/integrated; coordinator checkpoint was not edited.

Read the protocol and current checkpoint, full source diff and parent, complete fork bootdebug, overlapping reports 009/020/021, collector activation/install paths, MangoHud build/overlay-install consumers, thermal callers/readers and battery/HUD consumers. Historical memory supplied preservation context only; current source comparisons establish preservation below.

## CPU selection and consumers

The new 0007 patch changes only `check_thermal_zones` in MangoHud. `scripts/build-mangohud-in-rootfs.sh` downloads **v0.8.4**, applies the Qualcomm patches in filename order, then would build mangoapp. Both common and SM8750 overlay installers install an existing MANGOHUD_BUILD mangoapp, or retain stock if it is absent. The separately vendored MangoHud tree is not this builder's input; it is unchanged. No binary was rebuilt or installed, so this integration alone does not update an existing image, cached artifact or installed overlay.

Reviewed the exact v0.8.4 cpu.cpp fetched from `https://raw.githubusercontent.com/flightlessmango/MangoHud/v0.8.4/src/cpu.cpp` (SHA256 `d68c856a25514ac1e6a55599a3e5d4b266fc1cad6563938633fc2355d05dbb51`) as well as the local copy. None of patches 0001–0006 changes cpu.cpp. The 0007 patch is retained byte-for-byte from the assigned source.

- Existing hwmon/custom-sensor selection remains first. Thermal scanning is entered only when the caller's path is empty; this is not a replacement for all hwmon handling.
- Scan thermal_zone entries with `cpuss-` or `cpu-` type prefixes. Parse the temp as a long in millidegrees; missing/unreadable/empty/invalid/out-of-range conversion yields no usable value via the existing read_line behavior and catch. Skip values <= 0.
- A positive cpuss reading wins even if a per-core cpu reading was encountered earlier. Otherwise retain the first positive cpu candidate and use it after scanning. This is directory iteration order, not hottest-core selection or an average.
- The sensor remains a sysfs temp file. `ReadcpuTempFile` still reads an integer and divides by 1000 exactly once. The overlay's CPU-temperature enablement uses `GetCpuFile`, and its update path uses `UpdateCpuTemp`; there is no new scaling in the selector.
- This shared fallback uses sensor-name capability checks, not a board-name heuristic. It does not apply SM8750-specific paths to EVO. EVO's existing positive cpuss candidate retains precedence; zero/invalid candidates can now be skipped on any board using this fallback. Other valid hwmon routes remain unchanged.

The source specifically targets an initial zero cpuss reading reported on 8 Elite. Actual sensor availability and readings on 8 Elite/EVO were not observed here. Limitations retained: a selected hwmon input can still bypass this fallback even if it reads zero; a cached file is not reselected if readings later fail/change; no usable sensor at initialization can disable CPU-temperature display until reinitialization; valid nonpositive temperatures are intentionally excluded; `std::stol` permits a numeric prefix with trailing junk; enumeration order is not deterministic. These are not claims that the patch resolves every thermal failure.

## Charging diagnostics, semantics and repair

The source adds supply `uevent` and USB-C role/mode/orientation reads to each of the ten boot-summary passes (initial pass, then nine 20-second intervals plus command time). The existing summary.txt overwrite behavior is retained. These fields are not added to the later 30-minute performance samples, the screen pages or the separate opted-in upload archive. Missing classes/attributes produce no invented numeric measurement.

Supply names remain bracketed; only the leading POWER_SUPPLY_ key prefix is replaced by indentation. Status spelling (Charging, Discharging, Not charging, Full, Unknown), signs, numeric magnitudes, units implied by the driver attributes, USB type choices and role markers are retained. USB ONLINE or a PD mode/limit does not itself establish that the battery is charging, nor is a negotiated limit measured battery input power. The four typec attributes remain optional read-only reads; the collector does not set roles, current limits, charging state or thermal controls.

**Scoped repair:** add `[ -e "$p" ] || continue` to the power-supply loop, matching the source's typec guard. With an absent/empty class or dangling link the original glob printed a phantom `[*]`/missing-supply heading. A temporary fixture reproduced the source behavior and verified the repair. Clarified the two source comments to describe raw driver-reported evidence without promising an inferred charging rate. Only these two comment lines and the guard differ from upstream's added block.

Reviewed the actual v0.8.4 + existing patches battery consumer as well as the vendored variant: getPower records status and returns zero for Charging/Unknown/Full; the HUD uses nonzero current_watt to show wattage/time. The debug addition neither calls nor changes this logic. The patched builder's existing battery code differs from the vendored copy and includes inherited measurement assumptions (including a power_now fallback divisor of 10000000 and a time_to_empty_avg path). Those battery calculations are outside this two-file source change; raw supply logs are not interpreted through them or evidence of their accuracy.

## Fork preservation

Removing exactly the four added lines reproduces the complete starting bootdebug byte-for-byte. This preserves the exact ayaneo,pocketevo gate, release/pstore/runtime/audio/sleep/performance collection, DONE markers, USB ancestry/candidate retry and mount ownership/cleanup, exact screen/upload opt-ins, pre-stop display snapshot, private upload handling and parent waits. The normal initramfs-generated and fallback service activation/install paths remain unchanged.

Only the new MangoHud patch, bootdebug and this report differ from starting main. In particular EVO UFS remains bound through its existing sleep path; USB recovery, MCU, Wi-Fi restore/scan, Android LED semantics, audio/UCM and display/Gamescope/kernel policies are unchanged. No .env, secrets or gitignore edit.

## Checks and results

- `sh -n external-and-mods/kernel-common/initramfs/bootdebug`: PASS.
- `/tmp/worker039-checks.py`: PASS. Downloaded only five original v0.8.4 text source files used by the patch series into a temporary directory; applied all seven patches with `patch --batch --fuzz=0 -p1`: zero rejects, offsets or fuzz. No build script, compiler or package manager ran. Confirmed the CPU diff is confined to the fallback function, with caller/hwmon selection and milliC-to-C reader unchanged. This validates patch applicability and source boundaries, not compiled C++ execution.
- Same temporary harness: PASS, seven actual shell-fragment fixture scenarios. Empty-class source regression/repair, five battery status values, and missing uevent. Also covered real temporary symlink entries/dangling links, negative current, raw voltage/capacity/PD limits, unknown keys, partial typec attributes and attribute-less partner. All sysfs paths redirected to temporary synthetic files; no real sysfs/device read or write. Source output matched integrated output for populated entries after removing the source's phantom dangling-link heading.
- `python3 -B scripts/tests/test-pocket-evo-isolation.py Isolation.test_extra_debug_collection_is_inert_on_other_boards`: PASS, one existing relevant mock test. Broader unrelated tests/build-prefix probes were not run.
- Complete prior collector byte comparison and assigned thermal patch byte comparison: PASS. Product changed-path review and empty unresolved index: PASS.
- Ordinary diff whitespace check on bootdebug/report: PASS. Default whole-diff check flags five single-space blank context lines and final blank context line in the new, unchanged upstream unified patch. These are patch syntax, retained deliberately. Whole-diff check with `-c core.whitespace=-blank-at-eol,-blank-at-eof`: PASS; exact-context patch application above independently verifies the patch. No repository Git setting was changed.

Temporary tests are not committed ceremonial tests. Final response records commit/push outcome, independent remote equality, source ancestry, clean main and absent MERGE_HEAD.

## Remaining boundary

No build, compile, package compilation, build-script execution, VM/container startup, installation, flash, deployment, reboot, mount or real device/sysfs operation occurred. C++ runtime behavior, actual thermal names/values/units on each target, rootfs dependencies, sysfs permission/driver behavior, USB-C negotiation and charging rates remain device/image validation work. Shared sysfs reads can still fail or block and this source adds no per-read timeout; summaries are sequential observations rather than an atomic power snapshot. The uploaded archive is unchanged and does not automatically include these new local summary fields. No hardware success is asserted.
