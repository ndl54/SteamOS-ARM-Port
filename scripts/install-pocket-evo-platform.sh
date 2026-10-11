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
