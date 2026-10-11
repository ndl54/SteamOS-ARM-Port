#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
R=${1:?usage: install-pocket-evo-platform.sh ROOTFS}
for path in usr/share/alsa/ucm2/AYANEO/Pocket/HiFi.conf usr/share/alsa/ucm2/AYANEO/PocketEVO/HiFi.conf usr/share/alsa/ucm2/conf.d/sm8550/ayaneo-AYANEOPocketEVO-.conf; do
  install -D -m644 "$ROOT/sm8550-overlay/$path" "$R/$path"
done
# Restore the vendor policy in older test rootfs images; the generator masks
# it only when the running board's DT compatible is Pocket EVO.
install -D -m644 "$ROOT/steamos-overlay/usr/lib/systemd/user/plasma-plasmashell.service.d/99-odin-wayland.conf" "$R/usr/lib/systemd/user/plasma-xdg-desktop-portal-kde.service.d/99-odin-wayland.conf"
install -D -m755 "$ROOT/sm8550-overlay/usr/lib/systemd/user-generators/pocket-evo-portal" "$R/usr/lib/systemd/user-generators/pocket-evo-portal"

install -D -m755 "$ROOT/sm8550-overlay/usr/lib/pocketevo/pocket-evo-controller" "$R/usr/lib/pocketevo/pocket-evo-controller"
install -D -m644 "$ROOT/sm8550-overlay/usr/lib/systemd/system/pocket-evo-controller.service" "$R/usr/lib/systemd/system/pocket-evo-controller.service"

install -D -m755 "$ROOT/sm8550-overlay/usr/lib/pocketevo/pocket-evo-power" "$R/usr/lib/pocketevo/pocket-evo-power"
install -D -m644 "$ROOT/sm8550-overlay/usr/lib/systemd/system/pocket-evo-power.service" "$R/usr/lib/systemd/system/pocket-evo-power.service"
# SteamOS may already have a persistent /etc upper layer in a repacked rootfs.
mkdir -p "$R/etc"
for etc in "$R/etc" "$R/var/lib/overlays/etc/upper"; do
  [[ -d "$etc" ]] || continue
  mkdir -p "$etc/systemd/system/multi-user.target.wants"
  for unit in pocket-evo-controller.service pocket-evo-power.service; do
    ln -sfn "/usr/lib/systemd/system/$unit" "$etc/systemd/system/multi-user.target.wants/$unit"
  done
done

# Full builds copy Gamescope's scripts too; repacks need the EVO profile explicitly.
for prefix in usr usr/local; do
  install -D -m644 "$ROOT/external-and-mods/gamescope/scripts/10-steamos-arm/pocket-evo.icna3512.lua" "$R/$prefix/share/gamescope/scripts/10-steamos-arm/pocket-evo.icna3512.lua"
done
install -D -m755 "$ROOT/steamos-overlay/usr/lib/steamos/gamescope-session" "$R/usr/lib/steamos/gamescope-session"
