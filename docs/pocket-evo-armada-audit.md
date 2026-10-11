# Pocket EVO Armada parity audit

Audit started 2026-10-11. This is source/build evidence, not device validation.

## Baseline and preservation

- Armada: `1e2802a9101a4ba0cfff17b14ca41dec2ae5154e`, main, clean.
- SteamOS: `c9010f5be7a4474600343ef526cc8ee307dc0f41`, main, clean.
- Adjacent build directory is not a Git repository. Existing artifacts are preserved.
- No on-disk AGENTS.md found in these repositories or workspace ancestors; user-provided instructions apply.
- LED/RGB commit `2e14eba` is protected. Baseline hashes of all extant files touched by that commit: [preservation manifest](audit/pocket-evo-preserved-files.json). Some shared files also contain later changes; hashes record current HEAD, not the old commit. No LED protocol, service, UI or driver changes are authorized by this audit.
- Existing Colima profile resumed, no reset/reinstall. ROCKNIX checkout verified at `1ebff24f36501fb6493beb2bf83bf2604536d9aa` (20260901). Cached Linux 7.2.8 under `/work/kernel-sm8550` will not be modified.
- Final compilation: kernel, InputPlumber and Gamescope PASS. Gamescope passed on the explicitly authorized follow-up after the namespace repair (two compilation invocations total); kernel/InputPlumber remain at one compilation each. Original failure history is retained below.

## Build chain

`kernel-pocketevo/build.sh` → `kernel-common/build.sh pocketevo` → `kernel-pocketevo/soc.env` → SM8550 7.2 recipe. ROCKNIX 7.2/mainline/SM8550/default patches, then kernel-sm8550, then kernel-pocketevo; PATCH_SKIP applies to every directory. ROCKNIX DTS is copied AFTER patches, then local DTS copies and `.append` files. Consequently pre-copy board patches can be overwritten; board changes must use the local DTS phase. Only EVO DTB is accepted by the recipe.

## Progress

A–F source comparison and implementations complete. Kernel/package and InputPlumber verified. Gamescope rebuild, all 74 Meson tests, unfiltered tests and package verification PASS in the authorized 2026-10-11 follow-up. All hardware checks remain pending. Next: test the five modes and lifecycle on EVO. See final validation below.

## A. Buttons and controller

| ID | Problem/effect | Armada reference | SteamOS location | Initial status | Decision/change | Checks and hardware remaining |
|---|---|---|---|---|---|---|
| A1–4 | Four GPIO keys must emit press/release without typing or grabbing volume | kernel/dts/qcs8550-ayaneo-pocketevo.dts | kernel-sm8550/dts/qcs8550-ayaneo-pocketevo.dts.append | already equivalent | GPIO 85/169/170/91 active-low, pull-up, debounce 15ms, F13–16, separate aya-keys | Source compared; compiled DTB passed; device press/release required |
| A5–6 | QAM and paddles | inputplumber/capability_maps/ayaneo_pocket_evo_keys.yaml | sm8550-overlay/etc/inputplumber/capability_maps.d/ayaneo_pocket_evo_keys.yaml | already equivalent | F13 QAM, F14 L5, F15 L4, F16 R4 preserved; virtual Deck retained | Source compared; device Steam Input test required |
| A7–8 | MCU mode and controller lifecycle | device-quirks; ayaneo_mcu_xbox.yaml | pocket-evo-controller; platform installer; pocket-evo-sleep post | partial | Added missing-pad recovery at boot and native resume. Preserves already enumerated Xbox/DirectInput pad. Uses existing SerialLink lock without editing LED code. Existing Deck maps cover Guide, triggers, sticks and D-pad; InputPlumber is a system service across sessions | Four behavioral UART tests passed; physical enumeration and session/resume tests required |
| A9 | Avoid CPU spin in output-only haptics | inputplumber/patches/0004 | external-and-mods/InputPlumber/0001; scripts/build-inputplumber-konkr.sh | already equivalent when backend used | Existing 2ms poll retained; no extra backend enabled | Pinned rebuilt binary packaged; live active haptics backend still to check |
| A10 | Preserve user LED/RGB | not ported | commit 2e14eba and preservation manifest | already present | No changes | All10 manifest hashes pass; Linux LED12 and UI tests pass |

## Validation log

- Initial git status/branch/HEAD, all repositories: complete, clean main; build directory non-Git.
- Initial checkpoint: no compilation or hardware operation had been performed; final build outcomes below.

## B. OLED and mode provenance

| ID | Problem/effect | Armada reference | SteamOS location | Initial status | Decision/change | Checks / hardware remaining |
|---|---|---|---|---|---|---|
| B1 | Black screen from SM8750 mux/switch defer workaround | kernel 0509; board DTS | effective pmic_glink_altmode.c; SM8550 DT | already equivalent | The SM8750-only defer patch is absent in target; do not introduce it on SM8550. 9074 initializes Type-C match structs, 9075 clears stale UCSI role independently | Source traced; cold boot and external DP hardware pending |
| B2 | ICNA3512 power/reset/commands | kernel 0028 | 9073; PocketEVO DTS append | partial | Keep regulator/reset and DSC enable/disable sequence; EVO-specific descriptor, current mode chosen from CRTC mode on prepare | Full strict patch prepare passed; kernel compile passed; physical transitions pending |
| B3–4 | Landscape and touch across sessions | EVO DTS rotation270; Gamescope config | existing gamescope-session, panel-modes, KDE init, DRM rotation and touch transforms | already equivalent | Retain shader rotation fallback and existing touch rotation; do not replace with Fedora session machinery | Session tests pass; four corners in Gaming/Desktop and after resume pending |
| B5 | Nonlinear luminance and invalid DBV writes | kernel 0059/0060 | 9060 helper; 9073 driver | partial | Interpolate gamma2.2 curve; logical range0..4096, clamp EVERY output to DBV3413 including DT overrides; cache while disabled; restore DSI LPM on error | Source range/lifecycle review; actual luminance curve, lowest visible step and maximum heat need device measurement |
| B6 | Missing EDID/HDR profile | Gamescope 0002/3/4/5/6/7/0010/0019 | vendored Gamescope, EVO Lua, gamescope-session | missing | Synthetic EDID; exact EVO device ID match only without physical EDID; Gamma22 tonemap and metadata fallbacks. 780/390 nits and DCI-P3 are inherited estimates, NOT EVO measurements | Gamescope build and EDID/HDR C++ tests PASS; HDR gradients/metadata still device pending |
| B7 | Hardware color and 10-bit client buffers | kernel0068/69/70/76/77, Gamescope0017/0021 | 9061–64,9070; DRMBackend and WSI | missing | LUT DMA/DSPP and VIG colorops, ABGR/XBGR2101010; feature detected at runtime, shader fallback for unsupported transforms. Panel transport stays RGB888, DSC8bpc. No 10-bit panel or VRR claim | Kernel/Gamescope compiled; color/composition/WSI C++ tests PASS; HDR direct scanout not proven |
| B8 | Command-mode vblank time refers to wrong scanline | kernel0078 | 9066 | missing | Use tear counter to timestamp actual vblank | Source exact port; trace frame pacing on hardware pending |

### Five refresh rates (source support, all hardware pending)

Target HEAD and all local Git histories were searched: existing EVO ICNA3512 descriptor had 60/120 Hz; five-mode arrays for Lenovo/Redmagic are different panels and were not reused. Armada also has only 60/120. AYN commit `4c5e76e974db7cca853619ca138eecd8f004622f` provided the earlier 60/120 base.

The five complete timings **and per-rate initialization commands** come from [Teguh Sobirin / Aaron Kling ICNA35xx v3 patch](https://lore.kernel.org/r/20260514-icna35xx-v3-2-c304f04c32c4@gmail.com), also available in [Patchew](https://patchew.org/linux/20260514-icna35xx-v3-0-c304f04c32c4%40gmail.com/20260514-icna35xx-v3-2-c304f04c32c4%40gmail.com/). This is an ICNA3512 submission using the Odin2 Portal descriptor, NOT an EVO vendor Android dump or an EVO measurement. v4 dropped extra modes to simplify refresh lookup; its changelog does not report defective timing. No public EVO Android command dump was located. **Therefore 90/144/165 remain hardware-validation candidates, not established EVO operational support.**

[Machine-readable timing evidence](audit/pocket-evo-panel-timings.json) records exact porch, totals, clocks and calculations. Kernel compilation and synthetic-EDID timing roundtrip tests PASS for every row after the Gamescope follow-up; physical mode switching/selection and active refresh remain untested.

| Hz | Pixel clock kHz | H total | V total | Calculated Hz | Requested lane Gbit/s | DRM / command path | Hardware |
|---|---:|---:|---:|---:|---:|---|---|
| 60 | 355017 | 1260 | 4696 | 59.999899 | .912901 | preserved timing/commands, enumerated | not tested here |
| 90 | 354715 | 1260 | 3128 | 89.999949 | .912124 | v3 timing + 90Hz B3/B2/D3/CB/48 branch | pending EVO validation |
| 120 | 355017 | 1260 | 2348 | 119.999797 | .912901 | preserved timing/commands, DRM preferred | not tested here |
| 144 | 354896 | 1260 | 1956 | 143.999740 | .912590 | v3 timing + B3/B5/D9/CE/48 branch | pending EVO validation |
| 165 | 387933 | 1202 | 1956 | 164.999796 | .933363 | v3 timing + 48=20 branch; reduced HFP98 | pending EVO validation |

Refresh = clock_kHz*1000/(htotal*vtotal). All modes: active1080x1920, Hsync1/HBP23, Vsync1/VBP15. HFP156 except165=98; VFP2760/1192/412/20/20. DSC1.1, two540x20 slices,8bpc,8bpp,4DSI lanes. Effective MSM host compression computes htotal'=htotal-1080+360; pclk=floor(clockHz*htotal'/htotal); byteclk=floor(pclk*24/32); lane rate=byteclk*8. These are clock REQUESTS; actual PLL rounding requires live clk_summary/DSI trace. PHY SM8550 PLL range600MHz–5GHz; requested bit clock .913–.933GHz lies inside it. DPU MDP OPPs200/325/375/514MHz remain unchanged. At165, DSC active payload2.737152Gbit/s and four-lane aggregate3.733452Gbit/s; framebuffer read at4bytes/pixel~1.369GB/s, below catalog bandwidth limits but not a multi-layer or thermal guarantee.

9073 preserves120Hz as first/preferred kernel mode; Gaming Mode keeps existing60Hz default. `panel-modes --rates`, session rate forwarding, DRM connector mode collection and Lua known-display fallback preserve all five enumerated rates. `drm_set_refresh` rejects unlisted EVO rates instead of inventing VFP/pixel clocks. Existing saved connector mode handling remains. Mode set uses a full DRM disable/prepare/enable transaction, not a claimed seamless VRR switch. No VRR advertised. HDR is a display-level Gamma22 conversion capability, not proof that each rate works in HDR; test SDR first at each rate then HDR, session transitions and resume. Old Gamescope binary from a kernel-only repack is gated out of the new HDR session flag by its CLI capability.

## C. Sleep and power

| ID | Problem/effect | Armada reference | SteamOS path | Initial status | Decision/change | Checks / hardware remaining |
|---|---|---|---|---|---|---|
| C1–2 | GPIO/volume wake causes unintended resumes | EVO/common DTS | kernel-sm8550 DTS appends; pocket-evo-sleep | partial | Existing aya-keys no wake; delete VolumeUp wake; removed sleep helper re-enabling generic gpio-keys. Keep PMIC power key | DTS source checked; compiled DTB passed; physical wake matrix pending |
| C3 | PCIe WAKE# wrong polarity | common DTS | common append GPIO96/99 ACTIVE_LOW | equivalent | preserve | Compiled DTB passed; Wi-Fi/USB resume pending |
| C4 | SM8550 PCIe suspend resource floor |0512/13/20/22| common kernel patches and sm8550.dtsi | equivalent | skip L23 poll, suspend OPP, endpoint-only veto | source compared; repeated suspend pending |
| C5 | s2idle regulator state / codec rail |0523–26/commonDTS| common patches; l10b LPM append | equivalent | opt-in regulator mem state, no duplicate patch | source compared; rail/power measurements pending |
| C6 | Renesas poweroff loses firmware |0537|9056; Renesas rootfs firmware| equivalent | cache/reload with error propagation retained | firmware package check passed; pad enumeration after resume pending |
| C7 | Streams hold AudioReach graph during sleep |0528–30|common patches + audio userspace pre/post| equivalent | card suspend and graph release/open; existing single restore path | session behavioral tests pass; live game stream resume pending |
| C8 | UFS clocks/IRQ/unsupported queries/timeouts |0510/11,0533/35/36,device-quirks|9033,9067/68,pocket-evo-power|partial|keep laneclock+IRQ fixes; add fast unsupported-IDN failure, disable unsupported timestamp; set exposed UIC timeout3000ms|strict source prepare passed; fault/resume tests pending|
| C9 | Thermal IRQ aborts suspend |0204|common kernel thermal patch|equivalent|preserve mask/restore lower threshold IRQ|source checked; hardware trace pending|
| C10 | IPCC masking loses charger events in s2idle |0504|9072|partial|restore IRQF_NO_SUSPEND; mask only true suspend-to-RAM, late/early callbacks|source checked; unplug/replug during sleep pending|
| C11 | UART PM/IRQ balance |0534,1006|9034 + common IRQ-mask patch; uart11 MCU|equivalent|non-console IRQ mask and forced runtime PM already present; no RSInput child on EVO UART, preserve userspace serial owner|source checked; UART after repeated resume pending|
| C12 | Fan while charging asleep |0532,device-quirks|9071,pocket-evo-power/service|missing|driver feature added with default0; userspace opt-in only. Preserve7.2 timer_shutdown_sync. Check PWM provider before claiming operation|5 behavioral policy tests passed; hardware airflow/charging-event validation required|
| C13 | Competing fake/native suspend hooks |Fedora device policy|EVO sleep service/helper and existing generators|equivalent|keep existing native s2idle and one EVO pre/post service; no Fedora fake sleep. MCU recovery is appended to same post hook|session tests pass; systemd graph and live cycles pending|

Fan policy: `/etc/pocketevo/power.conf` may contain `POCKET_EVO_SLEEP_CHARGING_PWM=80` (example only; choose a physically validated speed). Default0 does not enable charging fan. The boot service applies only on `ayaneo,pocketevo`, only exposed attributes, and validates0..255 before writes. Kernel PM8550 LPG PWM channel3,40us period, fan5V regulator and supply availability still determine actual behavior. Restart the power service after changing policy; do not confuse the presence of the patch with enabled cooling.

## D. GPU / common display

| ID | Problem/effect | Armada reference | SteamOS path | Initial status | Decision/change | Checks / hardware remaining |
|---|---|---|---|---|---|---|
| D1 | Adreno740 idle power/clock |0004,0120/21/22|ROCKNIX/common patches + A740 catalog|equivalent|IFPC, rail floors and QoS retained|effective source compared; GPU idle/power pending|
| D2–4 | Lost HFI response/deadlock/recovery boot IRQ |0620/21/22|9053/54/55|equivalent|preserve response bits, bounded coredump wait and GMU mask|strict prepare; real fault recovery pending|
| D5 | Clock/rotation/color |0002,0048a/b,0066/67/68–78|common clocks+rotation+QSEED;9061–66,9070|partial|existing clock/PHY/SM8550 rotation retained; add LUT/color/vblank. Adapt9070 to SM8550 rotation cfg, not SM8650/8750 symbols|kernel/Gamescope compiled and C++ tests PASS; scaler, gradients, frame pacing hardware pending|
| D6 | Mesa/Turnip compatibility |Mesa patches; Gamescope patches|existing Mesa recipe; vendored Gamescope|partial|Mesa sparse sync/IR3 bindless fixes already equivalent; A830 workaround not for740. Port Gamescope color/API work onto existing rotation/backlight support|Gamescope rebuild and all tests PASS; game/GL/Vulkan runtime pending|

## E. Audio

| ID | Problem/effect | Armada reference | SteamOS path | Initial status | Decision/change | Checks / hardware remaining |
|---|---|---|---|---|---|---|
| E1 | Wrong DSP/topology |AYANEO SM8550 DTS/firmware|kernel-common firmware packaging; SM8550-APS model|equivalent|Keep ADSP qcom/sm8550/ayaneo and SM8550-APS-tplg.bin; renaming model would break topology lookup|packaged paths passed; DSP boot pending|
| E2–3 | Stereo/mic/DP UCM and routing |AYANEO/Pocket/HiFi.conf|PocketEVO UCM + conf.d/sm8550; sm8550-audio-*|equivalent|current EVO stereo mixer/routing equivalent; keep source-contract fixes from c9010f5|session tests pass; L/R/mic/output switch hardware pending|
| E4 | Restore live streams |0528–30|common AudioReach patches + userspace|equivalent|seeC7|live game stream required|
| E5 | DP audio prepare with display off |0618|common DP audio patch|equivalent|retain|external monitor power-cycle pending|
| E6 | Wrong WSA2/amplifier/compander |0007–0011,0075|EVO WSA_CODEC_DMA_RX_0 + wsa884x|not applicable|no S2/FIT WSA2 channel-map/compander port; EVO uses first WSA stereo pair|DT/source compared; preserve UCM|

## F. Connectivity, battery, game compatibility, extra sweep

| ID | Problem/effect | Armada reference | SteamOS path | Initial status | Decision/change | Checks / hardware remaining |
|---|---|---|---|---|---|---|
| F1 | Slow reconnection after resume |NetworkManager patch / device policy|existing NM build patch + pocket-evo-wifi-wake|equivalent|last channel priority retained; preserve user-disabled Wi-Fi|session tests pass; AP resume latency pending|
| F2 | Repeated6GHz scans |wpa_supplicant patches|base wpa_supplicant2.10|not applicable to current base|affected newer crossed_6ghz_dom/last_scan_all_chan logic absent in2.10 source. Do not backport unrelated newer API patch|base binary version and upstream2.10 source checked; re-audit on base upgrade|
| F3 | ath12k scan priority/timeout |1020/1021|common kernel patches|equivalent|computed WMI scan priority and wiphy_delayed_work retained|source compared; scan/suspend stress pending|
| F4 | Stable MAC addresses |0501|common socinfo/btqca/ath12k patch|equivalent|preserve serial-derived local addresses|effective code checked; reboot MAC stability pending|
| F5 | SDHCI capability mask |commonDTS|common append removes sdhci-caps-mask|equivalent|preserve|compiled DTB passed; real card modes pending|
| F6 | Battery units / controls |0901/02/03|common battery fixes +9069|partial|existing CHARGE_FULL/NOW units retained; add charge-current limit only where firmware properties support it; no default current write|source checked; firmware support/readback pending|
| F7 | FEX input ABI / unaligned atomics |0504,0505/0505a|ROCKNIX/common patches|equivalent|preserve ABI and128-bit atomic emulation|source checked; real x86 game tests pending|
| F8 | Additional shared fixes |0517/0519,0619,0505msm_gem,0048PHY|9074/75 and existingcommon patches|partial|add Type-C match initialization and stale-role clearing; existing submitqueue priority,gem locking andPHY mux fixes retained|strict patch prepare; externalUSB/DP and game load pending|

Not ported: SM8750/A830/WCN7860/Oryon SSBS, SM8250 widebus/PM8150, PocketS2/FIT WSA2/compander, PocketDS second panel, RSInput MCU reset/supply/axis calibration, AYN SN3112 PWM regulator sleep, and unrelated panel/touch drivers. Names alone are not EVO evidence. Existing shared baseline drivers remain; no features are disabled to make a build pass. EVO UART is userspace MCU/LED, touch is FocalTech, Wi-Fi WCN7850, GPU A740.

## Patch validation and reproducibility

EVO sets `PATCH_FUZZ=0`. Eighteen pre-existing ROCKNIX/local patches relied on fuzzy Kconfig/Makefile or changed7.2 context. `patches/rebased/` supplies exact-context replacements at their ORIGINAL positions, with identical intended additions/deletions; no extra driver is enabled. These are context refreshes, not new EVO feature ports. In particular HEROIC HTR3212 remains byte-identical in effective driver source and is unrelated to EVO's preserved userspace LED. Three source files already lacked a final newline; refreshed patches carry explicit no-newline markers.

Prepared isolated source: `/work/kernel-pocketevo/linux-7.2.8`; original cached `/work/kernel-sm8550` unchanged. Full final chain `--prepare-only` passed with fuzz0; log in sibling build `audit/prepare-final.log`. Rebase discovery logs include initial fuzzy attempts solely to locate changed context, not accepted final application. Build evidence is recorded below after the ONE final compilation invocation.

Initial pre-build plan completed as logged below. The later authorized Gamescope rebuild is complete; remaining validation is on hardware. Missing hardware evidence is not a source/build pass.

Additional A8 finding: Armada InputPlumber0002 resets evdev force-feedback slots and composite IDs before target replacement/suspend. This also applies to EVO's XInput evdev source (not only RSInput). Added `InputPlumber/0004-reset-force-feedback-on-target-change.patch` after the existing three local patches and wired the build script. Exact InputPlumber0.81 commit matches Armada. Four-patch source preparation passed; binary rebuild is included in the single final build batch. Existing cached binary must not be called updated until replacement/hash verification succeeds.

Validation before compilation: power/wake5, controller4, session10 tests passed; LED12 passed on Linux (no skip), LED UI test passed. All10 preserved LED files match SHA256. Parsed effective panel C initializers match the published timing JSON and lane-bandwidth arithmetic for all5 rates. HTR3212 effective driver SHA256 before/after context refresh is `04493345559d4d2609d8975e76b184809e815ac64c5c140d0b4fe8c9eecda9e1`.

The builder lacked Rust; a private Rust1.93.1 toolchain is being fetched under `/work/pocketevo-inputplumber/{cargo,rustup}` without changing shell profiles or shared toolchains. Gamescope and InputPlumber will use the existing SteamOS rootfs read-only via bubblewrap; artifacts/source/cache are in separate writable directories. No image contents are modified.

Isolation regression initially failed its old fixed count of six replacement patches after adding independent feature patches. Updated it to require all six original replacements still suppress their originals, every new patch remains active, and strict overrides are scoped to the EVO recipe. No feature or test removed.

Final source checkpoint: all7 isolation tests pass; platform+sleep+unchanged LED installers exercised together in a temporary directory. Complete kernel patch preparation passes with fuzz0 and no reject. All18 context-refresh change sets reviewed; differences in diff layout only move unchanged lines between added/removed/context, with identical net edits. Private Rust1.93.1 ready; no shared toolchain changes.

ONE final build batch now started: sibling `audit/final-build-once.sh`; logs/output `audit-build-20261011/`. Kernel jobs6, Gamescope jobs2, InputPlumber jobs4, sequential. Kernel source is isolated, output has its own directory; rootfs remains read-only. No compilation retry is authorized by this batch; failures will be reported explicitly.

Final build preparation found two baseline environment/provenance errors BEFORE kernel or Gamescope compilation: default Frame firmware path missing, and the pre-existing Gamescope full hash `6edb42bffacb9650c0b3fd63fe2eee3c5f43c75a` is absent upstream (Git upload-pack and GitHub API). The existing cached WCN7850 amss/m3/board files match all THREE pinned SHA256 values, so a private copy is used through FRAME_FW_DIR. Gamescope subprojects are corrected to verified tag3.16.30 commit `ad2763da1c48860f649abfe842a087188dcb6e20`: its src/meson.build matches the vendored file apart from the pre-existing backlight source and version fallback. This keeps wlroots0.20 and matching pinned dependencies; no arbitrary current-HEAD upgrade. Corrected the unverifiable version suffix. Continue to the FIRST compilation of kernel/Gamescope after these preparation repairs; InputPlumber is already compiling once.

InputPlumber final build PASS (release, Rust1.93.1,2m29s), runtime `--version` prints0.81.0 in the read-only SteamOS root; ldd resolves udev/iio/gcc/m/libc/cap without missing dependencies. New binary+SHA copied into the existing pinned cache path consumed by install-inputplumber-sm8550.sh; therefore the FF reset patch is now in the packaging path, not just a loose patch. No live input device was opened by these version/link checks.

Verified Gamescope dependency pins from3.16.30: wlroots `d783533489e1f75d6886c2ab5c5960090ef268f8`, libliftoff `8b08dc1c14fd019cc90ddabe34ad16596b0691f4`, vkroots `5106d8a0df95de66cc58dc1ea37e69c99afc9540`, libdisplay-info `c67a3e9bedb05ab61c7443704a1a107e76254595`, openvr `ff87f683f41fe26cc9353dd9d9d7028357fd8e1a`. All five checked out successfully; staged cache records exact upstream ref. Catch2 official Meson support is supplied by pinned3.16.1 archive with SHA256 in `catch2.wrap` (3.8.1 has no meson.build and was rejected during preparation).

Actual shipped EVO Lua profile executed with LuaJIT from target rootfs: matches exact EVO+internal+no physical EDID; rejects another ICNA3512 board, external connector and physical-EDID connector. Pass. Kernel effective config confirms ICNA3512/MSM/IPCC/LPG built-in, pwm-fan/battmgr/ath12k/SC8280XP enabled as modules, XPAD built-in. Complete DTB/module/firmware artifact validation follows compilation.

Kernel final compilation and packaging PASS: Linux7.2.8 EVO, GCC15.3.1; Image/modules/dtbs and external chipone_tddi module built once. Output `audit-build-20261011/kernel/current/` (KERNEL19,902,464bytes). No image build/flash. There are compiler warnings, including pre-existing chipone_tddi missing prototypes; warnings were not suppressed. Full log retained.

Read-only packaged-output verification PASS: exactly EVO DTB, F13–F16 GPIO85/169/170/91 active-low/15ms, no VolumeUp/aya-key wake, PCIeWAKE96/99 active-low, panel EVO compatible+270° rotation, SDHCI mask absent, SM8550-APS model; required config options/modules, ADSP.mdt/topology/Renesas firmware exist. Initial verifier wrongly demanded a DT wakeup-source property on the power key; corrected it to the actual PMK8350 compatible + enabled PM8941 driver whose match data sets wakeup_source_default=true. No kernel change or rebuild was needed. Final verifier log `kernel-output-verified.log`.

Historical first-build result (resolved by the authorized follow-up below): Gamescope first compilation FAILED at DRMBackend.cpp:4729: the new global-scope `drm_set_refresh` guard used `GAMESCOPE_SCREEN_TYPE_INTERNAL` without its `gamescope::` namespace. Corrected that qualification in source. **No second compilation was run during that original request.** At that checkpoint, Gamescope binary, WSI packaging and its C++ test suite are NOT validated/complete after this source repair; meson configure/dependency resolution passed, but ninja stopped before finishing all targets and tests. Kernel and InputPlumber successes are independent. Logs preserve both the original dependency preparation failure and the actual compiler failure. This was an implementation-caused build-validation blocker; the follow-up below resolves it.

Armada InputPlumber0001 shares raw gamepad access with Waydroid by changing host hiding/grab semantics. This is not needed for the SteamOS virtual Deck path (no Waydroid consumer traced) and would change existing ownership rules, so it is intentionally not ported. It is unrelated to the Share/QAM button mapping. 0003 adds AYN Thor Lite matching, not EVO. 0004 polling fix was already equivalent; no new haptics backend enabled.

## Final validation summary and handoff

| Check | Result |
|---|---|
| Kernel patch chain | PASS fuzz0, no rejects;18 baseline context refreshes reviewed |
| Kernel/DTB/module build | PASS once,7.2.8-pocketevo-steamos;47 compiler warnings in baseline/shared drivers, not suppressed |
| Packaged kernel output | PASS DTB/config/modules/ADSP topology/Renesas and built-in WCN hashes |
| InputPlumber | PASS once; binary+SHA updated, target-rootfs version/ldd pass |
| Gamescope | PASS on authorized follow-up; all 74 Meson tests, 62 core/4 WSI unfiltered cases, CLI/dependencies and package verification PASS |
| Python behavior/regression | controller4 + power/wake5 + session10 + isolation7 PASS |
| LED/RGB | Linux12 + JS UI PASS;10 baseline file hashes unchanged |
| Actual Lua profile | PASS EVO match and three negative identity/connector cases |
| Mode arithmetic | PASS all5 effective C timings match independent evidence JSON; no physical measurement |
| Shell / whitespace | shell syntax and non-patch diff whitespace pass; unified patches validated by exact application |
| Hardware / image | NOT RUN; no image creation, flashing, bootloader change or device deployment |

Gamescope preparation was repaired without compilation (missing pinned commit). Kernel preparation was repaired without compilation (missing default firmware path). After those repairs, each component compiled once. Gamescope's actual compiler error was initially fixed without another compilation; the user subsequently authorized the successful rebuild recorded below. Kernel/DTB success alone does not establish Steam HDR or five selectable refresh rates in the final running stack.

Packaging: full image pipeline consumes kernel output and `GAMESCOPE_BUILD=/work/pocketevo-gamescope/build`; apply-overlays copies executable, WSI and Lua scripts and runs the platform installer. That Gamescope directory is now complete and tested following the authorized rebuild; an exported bundle is linked below. Kernel-only repack can use the successful kernel, but is not equivalent to the new complete display stack. Installer tests used a temporary directory, never the source image. InputPlumber installer verifies the new pinned SHA before copying the binary.

Artifacts/logs are in sibling `Steam-OS-ARM-PocketEvo-build/audit-build-20261011/`; source preparation/provenance files are in `audit/`. They are external build artifacts, not another Git repository. Reusable verification: `python3 scripts/verify-pocket-evo-kernel.py KERNEL_SOURCE PACKAGED_OUTPUT` reads only the resulting files. Firmware source overrides and subproject pins are documented above so future runs do not depend on chat history.

### Remaining verification

1. **Completed in the authorized follow-up:** rebuild Gamescope and run the full suite, including synthetic EDID roundtrips for all5 EVO timings, HDR color/composition, WSI enumeration, Lua identity and client-format policy. No test disabled or skipped. Hardware behavior is still pending in items2–5.
2. On separately authorized EVO hardware, capture DRM connector mode list (`modetest -M msm -c`), active DRM state, DSI/PLL clock summary and vblank/frame timestamps for every rate. Confirm actual rather than labelled refresh. Obtain EVO stock Android DTBO/panel command sequence if90/144/165 fail; the current provenance is the shared ICNA3512 submission, not an EVO dump.
3. At60/90/120/144/165: SDR mode set, brightness range, touch corners, Gaming/Desktop switch, saved rate restore, then HDR gradients and color pipeline. No VRR expectation, no claim of measured780/390nit or true10bpc panel transport.
4. Repeat native suspend/resume with a running audio stream and controller; check only power button wakes, USB pad/Renesas firmware, Wi-Fi last-channel reconnect, stable MAC, charging events with IPCC and fan opt-in. Validate codec/PCIe rail power and UFS errors from real logs. Check rumble after virtual target changes.
5. Test stereo L/R, mic, DP output/power cycle, microSD and representative FEX/x86 titles. These require hardware and were not substituted with source/build assertions.

Implementation commit and push evidence will be appended after final repository verification. Armada stays unchanged; build workspace is non-Git.

Final installer review: both new services are enabled in root /etc AND an existing SteamOS persistent /etc upper layer, matching this repository's repack layout. Actual temporary-root installation passed for both. Final binary-DTB verifier now also follows aya-keys pinctrl phandle and confirms all four GPIOs have pull-up. Pass; no recompilation needed for these verifier/installer checks.

[Artifact SHA256 and final build status](audit/pocket-evo-build-results.json). Mesa unchanged: target recipe26.2.3 already wires the two A740 patches; no new Mesa build required for this change.

## Commit and repository evidence

- Implementation/source/tests/audit commit: `bb37da456b64d5e2b86916b5b9dff53c1c98cfd4` on existing `main`.
- Push of implementation succeeded: `c9010f5..bb37da4 main -> main` to `origin` (`ndl54/SteamOS-ARM-Port`). No unrelated changes staged.
- Armada remains clean on `main` at `1e2802a9101a4ba0cfff17b14ca41dec2ae5154e`; no commit/push needed.
- Build directory remains non-Git. Logs, successful kernel/InputPlumber artifacts, the now-complete Gamescope build and private compiler caches are retained.
- Source image loop mount confirmed `ro,norecovery`, then unmounted and detached. The existing builder/profile is stopped after work, returning it to its initial stopped state. No image was modified.
- This final documentation-only update records the implementation hash and its verified push; its own hash is available in `git log -1 -- docs/pocket-evo-armada-audit.md`.


## Gamescope follow-up — 2026-10-11

User explicitly authorized rebuilding Gamescope after the namespace fix and continuing fixes/tests to PASS. The original one-build restriction remains historical for the first audit; this follow-up does not rebuild kernel or InputPlumber.

- Starting source: clean `main` at `3ad7c44339521e010fdf4e8471abb24174265f52`; Armada remains unchanged at `1e2802a9101a4ba0cfff17b14ca41dec2ae5154e`.
- Resumed the existing builder, source image mounted read-only with `ro,noload`; source staged into the previous task-owned build directory. Reusing the configured Meson/Ninja cache and verified dependency pins.
- Completed: incremental compilation PASS after the committed namespace repair; no further Gamescope source change was needed. Full tests and packaging PASS as detailed below.
- New logs/artifacts: sibling `Steam-OS-ARM-PocketEvo-build/gamescope-final-20261011/`. Original failed-build logs remain intact.


### Follow-up validation and deliverable

| Check | Result / evidence |
|---|---|
| Gamescope Ninja build | PASS, all remaining248 targets; GCC15.1.1 in the target rootfs. Second compilation invocation overall, first in this follow-up. No kernel/InputPlumber rebuild |
| Full Meson suite, including subprojects | **74 PASS,0 fail,0 skipped,0 timeout**; `logs/build-test-1.log`, package `logs/testlog.txt` and JSON |
| Unfiltered core suite | **62 cases /398 assertions PASS**; includes EDID timing roundtrips for60/90/120/144/165, display lookup, HDR/color policy and client formats |
| Unfiltered WSI suite | **4 cases /25 assertions PASS**; Vulkan surface enumeration behavior |
| Actual Lua profile | **4/4 PASS**: exact EVO/internal/EDID-less match; wrong board, external and physical EDID excluded |
| Target-rootfs runtime | `--version`, `--help` PASS; version3.16.30-steamos-arm. `ldd -r` on all4 executables and WSI has no unresolved library/symbol. Maximum Gamescope/WSI GLIBC requirement2.38, rootfs2.39 |
| Python regression | controller4 + isolation7 + LED12 + power5 + session10 = **38 PASS** in Linux builder |
| JS LED UI | PASS with existing host Node; initial combined Linux launcher reached a missing `node` executable after all Python tests passed. Reran JS on macOS successfully; no dependency installed and no test disabled |
| Package | ARM64 ELF verified, checksum manifest PASS; all copied binary/WSI/profile/looks/session bytes match build/source; packaged Vulkan manifest resolves to the supplied WSI library |
| LED/RGB | **10/10 protected SHA256 hashes unchanged**, no protected files edited |
| Physical device | Not tested; no compositor/DRM launch, image rebuild/flash, device installation or bootloader change |

Compiler warnings are retained (signedness, vendored sol2 array bounds and existing connector-name strncpy); none was suppressed. Unfiltered process tests intentionally use nonexistent dummy Steam overlay preload paths, producing loader diagnostics while their assertions pass; binary `ldd -r` checks are clean.

Final package (relative to workspace):
`Steam-OS-ARM-PocketEvo-build/gamescope-final-20261011/gamescope-3.16.30-pocket-evo-aarch64.tar.gz`.
SHA256: `c4c9727a73aff9d1b8544d1f7e197873497815f31b75f36b00f22128dfe0ff82`.
Extracted final executable: `gamescope-final-20261011/gamescope-3.16.30-pocket-evo-aarch64/build/src/gamescope` beneath the build workspace; SHA256 `5569058776cce77b1661bc0fdc3fbb491d085199ee70caa5836e3cf465a1a9db`.
WSI SHA256: `bff8f9cc2fe5a294f9ee4cdd3c35dda25fbcd78895b76b0bc30a212179f0a04f`.

The bundle contains `build/` usable as GAMESCOPE_BUILD by the existing pipeline, and a reviewed `runtime/` overlay with binaries, WSI+manifest, complete scripts/looks, backlight udev rule and matching session. README documents the required target file capabilities (tar does not preserve them), source/kernel requirements, no hardware claim and checksum verification. Nothing was installed onto a device. Both generated build paths and the packaged /usr WSI manifest are retained for their respective consumers.

Build source is exactly commit `3ad7c44339521e010fdf4e8471abb24174265f52` (Gamescope namespace fix already committed in `bb37da4`). This follow-up changes only audit evidence. No additional source fix was necessary after compilation/tests passed. Build/verification/package commands are retained as `build-and-test.sh`, `verify.sh`, `package.sh` alongside the artifact; old failed logs remain separate. On-disk JSON status now distinguishes historical build attempts from the final PASS.

Remaining blockers: no source/build/test blocker for Gamescope. Physical OLED timing, actual HDR/color/scanout, touch/session changes and sleep/resume still require EVO testing as listed above. A Gamescope-only bundle cannot expose modes absent from the running kernel/DTB. Defaults and hardware evidence limits are unchanged.

Cleanup verified: root image mount was `ro,relatime,norecovery`; unmounted and loop detached. Existing builder/profile stopped again after validation, preserving caches and exported artifacts. No environment reset or source-image write.
