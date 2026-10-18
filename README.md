<p align="center">
  <a href="https://steamos-arm-port.github.io/">
    <img src=".github/assets/logo.svg" alt="SteamOS ARM Port" width="112">
  </a>
</p>

<h1 align="center">SteamOS ARM Port — Pocket EVO fork</h1>

<p align="center"><strong>Unofficial SteamOS for Snapdragon handhelds</strong></p>

<p align="center">
  Valve's SteamOS for ARM, the one made for the Steam Frame, set up for handhelds
  and tablets: Game Mode, the KDE desktop, PC games through FEX and Proton, and Android apps.
</p>

<p align="center">
  <a href="https://github.com/hashtagbasit/SteamOS-ARM-Port/releases"><img alt="Upstream release" src="https://img.shields.io/github/v/release/hashtagbasit/SteamOS-ARM-Port?include_prereleases&style=flat&color=7c5cf0&label=upstream%20release"></a>
  <a href="https://steamos-arm-port.github.io/"><img alt="Documentation" src="https://img.shields.io/badge/docs-steamos--arm--port.github.io-18181a?style=flat"></a>
  <a href="LICENSE"><img alt="GPL-2.0 license" src="https://img.shields.io/badge/license-GPL--2.0-18181a?style=flat"></a>
  <a href="https://discord.gg/EP53nZYvg"><img alt="Discord" src="https://img.shields.io/badge/chat-Discord-5865F2?style=flat&amp;logo=discord&amp;logoColor=white"></a>
</p>

<p align="center">
  <a href="https://steamos-arm-port.github.io/getting-started/install/"><strong>Install it</strong></a>
  ·
  <a href="https://steamos-arm-port.github.io/devices/">Supported devices</a>
  ·
  <a href="https://steamos-arm-port.github.io/downloads/">Downloads</a>
  ·
  <a href="https://steamos-arm-port.github.io/help/known-issues/">Known issues</a>
</p>

> [!WARNING]
> This is an unofficial community fork, not affiliated with or endorsed by Valve.
> Bootloader, boot-image and internal-storage writes can leave a device unable
> to boot or erase data. Back up to a separate PC, identify the exact device and
> destination, and follow the instructions for that device and image. The
> handheld ROCKNIX ABL procedure is not the Lenovo tablet procedure.

## About this fork

This repository maintains AYANEO Pocket EVO changes on top of
[SteamOS ARM Port](https://github.com/hashtagbasit/SteamOS-ARM-Port).
The release badge, website and Discord above belong to upstream; they do not
certify a build from this fork. Pocket EVO notes cover the
[platform and build](docs/pocket-evo-build.md),
[sleep/wake](docs/pocket-evo-sleep-wake.md) and
[Android LED behavior](docs/pocket-evo-led.md). General architecture is in
[HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).

The upstream 1.4 feature overview below describes source integration, not a
fork 1.4 release. At review item 107 of the frozen 109-commit queue, no combined
build or device validation has been performed. The overlay recipes still
default to `STEAMOS_ARM_VERSION=1.3.0`; the EVO repack script still names its
`v1.3.2` base, and the Gen 5 test packager still uses `v1.3.0-testN` names.
A version label or an older image is not evidence that the integrated changes
are present. See the [integration reports](docs/upstream-sync-20261017/).

### Features in source

Availability depends on the device, built components and installed image:

- Game Mode and KDE Desktop Mode, with Steam Deck controller emulation on supported handhelds.
- x86 PC games through FEX and ARM64 Proton; Heroic for Epic, GOG and Amazon.
- Android app/Play Store integration and device-specific restart-to-Android controls in Handheld Control.
- Settings > System update integration, subject to a compatible package and configured update source.
- microSD boot on supported devices and internal installation on explicitly supported targets; internal installation can erase Android user data.
- External-display Game Mode support. USB-C DisplayPort monitor audio is temporarily disabled in the Odin 3 and Pocket FIT Elite UCM profiles to avoid a reported startup probe failure that can remove the whole sound card. Their DP backend/topology remain; USB Audio Class DACs/headsets are outside this change. Other devices remain device-dependent and unverified on this integrated fork; dock video does not establish working sound.
- Lossless Scaling frame generation through lsfg-vk 2.0 or Classic 1.x, Decky and the performance overlay.
- Steam Remote Play hardware-decoder integration and optional PyroWave; actual decode/performance support requires device validation.
- Loadout selections for the SoC, sleep/fan policies and low-battery shutdown handling; battery life and reliable shutdown are not established by source review.
- A themed bottom-screen dashboard for AYN Thor and AYANEO Pocket DS.

Known source-level limits remain: [093](docs/upstream-sync-20261017/093-f1058a0.md)
withholds automatic Steam desktop keyboard fitting;
[098](docs/upstream-sync-20261017/098-6d2e85c.md) leaves S2 system volume under
software mixing despite the new UCM controls; and
[103](docs/upstream-sync-20261017/103-924a80f.md) bounds some brightness jumps
but does not provide panel calibration or eliminate first-sample/gradual
outlier errors. These are not fixed-hardware claims.

## Quick start: supported ROCKNIX ABL handhelds

This is a checklist for a matching, verified image, not an instruction to
install the unbuilt integration tree or to use an arbitrary upstream update
on a customized EVO image.

1. Confirm the exact model, SoC, image provenance and recovery procedure. Save your data and stock ABL backups off-device before changing bootloaders. Keep existing backup/checksum pairs; do not overwrite them or bypass refused target checks.
2. Obtain all archive parts for that image. For upstream split `.7z` images, keep every part together and open `.001` with 7-Zip. Verify the supplied checksum, extract the `.img`, then select and verify the destination microSD card (32 GB or larger) in balenaEtcher or Rufus. Writing the image erases that card. [Upstream releases](https://github.com/hashtagbasit/SteamOS-ARM-Port/releases) are separate from this fork's build evidence.
3. Follow the [upstream ABL guide](https://steamos-arm-port.github.io/getting-started/abl/) for the supported handheld and its matching image's ABL folder. Read the script's write scope before deliberately running it as root: it writes both ABL slots. Preserve its SoC, slot, checksum, backup and readback checks; retain the backups and checksum files on your PC.
4. Boot the card through the ABL menu and select the exact device. First-boot duration varies; reaching the menu or a successful write does not prove that SteamOS boots correctly.

For an already installed system, Settings > System > Check for updates uses
the installed update agent. This tree's agent queries upstream GitHub releases,
not a dedicated Pocket EVO fork feed. Confirm that any offered package is intended for
that device and preserves the required fork changes before applying it.

For internal storage, read the [installer's scope and erase warnings](external-and-mods/ufs-install/README.md).
Confirm the target and plan, keep backups off-device, and retain administrator
authentication and explicit erase consent. `--resume` is a destructive reinstall,
not an update; do not bypass unsupported-device, mounted-target or layout checks.

## Devices

The status labels below are **upstream's claims at source `56a30d7`**, retained
for orientation. They are not fork build results or hardware certification.
The new SM8250 kernel/DTB and Gen 5 Baldur sources exist in this tree; a listed
device or source recipe alone does not prove that a working image is available.

### Handhelds

| SoC | Devices | Upstream status at source |
|---|---|---|
| Snapdragon 8 Elite | AYN Odin 3, KONKR Pocket FIT Elite | Stable |
| Snapdragon 8 Gen 3 | KONKR Pocket FIT, AYANEO Pocket S2 / S2 Pro | Stable |
| Snapdragon 8 Gen 2 | AYN Odin 2 / Mini / Portal / Thor, AYANEO Pocket ACE / DMG / DS / EVO / S 1K / S 2K, Retroid Pocket 6 / Nova | Stable |
| Snapdragon 865 | Retroid Pocket 5 / Flip 2 / Mini / Mini V2, AYN Thor Lite, MANGMI Air Y Pro / Pocket Max, AYANEO Pocket MICRO 2 | Beta |

Upstream groups handheld images by SoC and selects the model through ABL.
This fork also has a dedicated Pocket EVO recipe/repack path; its outputs must
not be treated as universal SM8550 images. Community test reports for upstream
images do not validate this integrated fork.

### Phones & tablets

| Device | SoC | Upstream status at source |
|---|---|---|
| Lenovo Legion Y700 Gen 3 (TB321FU) | Snapdragon 8 Gen 3 | Beta |
| Lenovo Legion Y700 Gen 4 (TB322FC) | Snapdragon 8 Elite | Beta |
| Lenovo Legion Y700 Gen 5 (TB323FU) | Snapdragon 8 Elite Gen 5 | Testing |
| REDMAGIC 6 (NX669J) | Snapdragon 888 | Build it yourself ([guide](docs/redmagic6.md)) |

Gen 3 and Gen 4 have separate tablet/internal-storage paths; these can erase
Android user data and write boot partitions. Gen 4 microSD support is an
upstream claim here, not a result verified by this review. Confirm the exact
model and image instructions rather than applying the handheld ABL steps.

Gen 5 (TB323FU / Baldur) has a separate microSD/Android switch path. Its
[host installer](scripts/gen5/install-gen5.sh) requires the packaged files,
rooted Android with shell access and the expected ZUI `18.0.12.104` firmware;
compatibility with other firmware is not established. It validates the exact
board and active slot, preserves boot backups and checks write/readback targets.
Keep the PC backups and do not bypass these checks. The default invocation
already performs writes, including preserving Android in `boot_b` when needed
and staging firmware/boot files; it is not a dry run. `--switch` additionally
writes the prepared SteamOS image to `boot_a` and requests reboot. Per [review 104](docs/upstream-sync-20261017/104-aac085b.md),
exit 2 after switching means the boot write verified but the reboot request is
**unconfirmed**. Check the tablet before retrying; even a successful reboot
command is not evidence of successful SteamOS boot. The SD workaround is a
100 MHz clock ceiling, not a guarantee of SDR50 mode or card stability.
The shared Android backup-hash failure handling recorded in
[review 101](docs/upstream-sync-20261017/101-71fd544.md) remains pending global
review; these checks do not establish a safe or validated install.

The [upstream Lenovo page](https://steamos-arm-port.github.io/devices/lenovo/)
and Discord are background resources. At this review the website still has
older Testing/no-TB323FU guidance, so it must not be used as proof of the
new README's Beta labels, Gen 5 readiness or a compatible fork release.

## Documentation

Fork-specific evidence lives in the local docs linked above. The following
[website](https://steamos-arm-port.github.io/) and support links are upstream
resources and may describe different images or older device support.

| I want to… | Guide |
|---|---|
| Install it | [Flash to a microSD card](https://steamos-arm-port.github.io/getting-started/install/) |
| Check my device | [Supported devices](https://steamos-arm-port.github.io/devices/) |
| Move it to internal storage | [Internal storage](https://steamos-arm-port.github.io/getting-started/internal-storage/) |
| Update | [Updates](https://steamos-arm-port.github.io/using/updates/) |
| Get help | [FAQ](https://steamos-arm-port.github.io/help/faq/) · [Troubleshooting](https://steamos-arm-port.github.io/help/troubleshooting/) |
| Report a bug | [GitHub issues](https://github.com/hashtagbasit/SteamOS-ARM-Port/issues) |

## Building

Image recipes target ARM64 Linux; see [docs/building.md](docs/building.md)
and the [Pocket EVO notes](docs/pocket-evo-build.md). The frozen queue requires
its combined validation/build after all 109 items; this README update does not
produce or validate an image. Issues and pull requests are welcome,
and for help with installing come say hi on [Discord](https://discord.gg/EP53nZYvg).

## Supporting upstream

<p align="left">
  <a href="https://ko-fi.com/aimalb"><img src="https://img.shields.io/badge/Ko--fi-Buy%20me%20a%20coffee-ff5e5b?style=for-the-badge&logo=kofi&logoColor=white" alt="Ko-fi"></a>
  <a href="https://paypal.me/Basit2000"><img src="https://img.shields.io/badge/PayPal-Basit2000-00457c?style=for-the-badge&logo=paypal&logoColor=white" alt="PayPal"></a>
</p>

The donation links above support the upstream maintainer and their device work.

Have a device you'd like to see supported? Sending one over for long term
development can help upstream; contact its maintainer on
[Discord](https://discord.gg/EP53nZYvg).

## Credits

The kernels and device support build on [ROCKNIX](https://github.com/ROCKNIX/distribution),
with fixes shared back and forth with other ARM handheld projects. Thanks to
everyone who contributed code, and to the testers in the Discord who send logs
across devices. The full list of projects and people is in [CREDITS.md](CREDITS.md).

## License

The scripts and overlays are GPL-2.0, everything in `external-and-mods/` keeps
its own license. See [LICENSE](LICENSE).

Steam and SteamOS are trademarks of Valve Corporation, used here only to say
what this is based on. Please don't ask Valve for help with it.
