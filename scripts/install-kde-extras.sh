#!/usr/bin/env bash
# Bluetooth and display settings for Desktop Mode (bluez-qt, bluedevil,
# libkscreen, kscreen), built inside the Frame rootfs by
# build-kde-extras-in-rootfs.sh. Valve's aarch64 repos don't carry them.
#
# Usage: install-kde-extras.sh <rootfs>
# KDE_EXTRAS points at the kde-extras.tar (default: the build's usual place).
# Without the default archive, keep the existing rootfs and fallback behavior.
# An explicit KDE_EXTRAS must exist; a typo must not silently omit the feature.
# Only use trusted archives produced for this rootfs; this is not a package manager.
set -euo pipefail

R="${1:?rootfs}"
T="${KDE_EXTRAS:-${STEAMOS_WORK:-/work}/kde-extras-build/kde-extras.tar}"

[[ -d "$R/usr" && "$(cd "$R" && pwd -P)" != / ]] \
  || { echo "ERROR: expected a staged rootfs, not the host root" >&2; exit 1; }

if [[ ! -s "$T" ]]; then
  if [[ -n "${KDE_EXTRAS:-}" ]]; then
    echo "ERROR: explicit KDE_EXTRAS archive is missing or empty: $T" >&2
    exit 1
  fi
  echo "WARNING: no $T: leaving existing KDE components/fallbacks unchanged" >&2
  echo "         (scripts/build-kde-extras-in-rootfs.sh builds it)" >&2
  exit 0
fi
tar -C "$R" --no-same-owner -xf "$T"
for f in usr/lib/qt6/plugins/plasma/kcms/systemsettings/kcm_bluetooth.so \
         usr/lib/qt6/plugins/plasma/kcms/systemsettings/kcm_kscreen.so \
         usr/lib/qt6/plugins/kf6/kded/bluedevil.so usr/lib/qt6/plugins/kf6/kscreen/KSC_KWayland.so \
         usr/lib/libKF6BluezQt.so.6 usr/lib/libKF6Screen.so.8 \
         usr/lib/qt6/qml/org/kde/bluezqt/qmldir \
         usr/lib/qt6/qml/org/kde/bluezqt/libbluezqtextensionplugin.so \
         usr/share/plasma/plasmoids/org.kde.plasma.bluetooth/metadata.json \
         usr/bin/bluedevil-wizard usr/bin/bluedevil-sendfile \
         usr/lib/kscreen_osd_service usr/lib/kf6/kscreen_backend_launcher \
         usr/share/dbus-1/services/org.kde.kscreen.service \
         usr/share/dbus-1/services/org.kde.kscreen.osdService.service \
         usr/lib/systemd/user/plasma-kscreen.service \
         usr/lib/systemd/user/plasma-kscreen-osd.service; do
  [[ -s "$R/$f" ]] || { echo "ERROR: $f missing after unpacking $T" >&2; exit 1; }
done
for f in usr/bin/bluedevil-wizard usr/bin/bluedevil-sendfile \
         usr/lib/kscreen_osd_service usr/lib/kf6/kscreen_backend_launcher; do
  [[ -x "$R/$f" ]] || { echo "ERROR: $f is not executable" >&2; exit 1; }
done
echo "kde-extras: Bluetooth and display settings installed"
