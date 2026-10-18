#!/usr/bin/env bash
# Build the KDE pieces the Frame rootfs leaves out, inside that rootfs (its
# Qt, KDE Frameworks and Plasma; final linkage still needs validation):
#
#   bluez-qt + bluedevil  Bluetooth in Desktop Mode (tray applet, System
#                         Settings page, pairing wizard, file transfer)
#   libkscreen + kscreen  Display settings: scale, orientation, resolution,
#                         refresh rate, plus the OSD and the kded module
#
# Supplement the Frame baseline. The EVO fork also has a separate KScreen
# fallback in apply-overlays.sh; a supplied bundle satisfies that check.
#
# Usage: build-kde-extras-in-rootfs.sh <rootfs> [out-dir]
# Leaves <out-dir>/kde-extras.tar (paths relative to /), which
# install-kde-extras.sh unpacks into an image's rootfs.
set -euo pipefail

R="$(cd "${1:?rootfs}" && pwd -P)"
WORKDIR="${STEAMOS_WORK:-/work}"
OUT="${2:-${WORKDIR}/kde-extras-build}"
SRC="${WORKDIR}/kde-extras-src"

# Frameworks and Plasma releases the Frame rootfs ships (its CMake config
# files: KF6CoreAddons, LibKWorkspace).
KF_VER="${KF_VER:-6.14.0}"
PLASMA_VER="${PLASMA_VER:-6.2.5}"
KDE_MIRROR="${KDE_MIRROR:-https://download.kde.org/stable}"

log() { printf '==> [kde-extras] %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v bwrap >/dev/null || die "bwrap required (apt install bubblewrap)"
[[ -x "$R/usr/bin/cmake" && -x "$R/usr/bin/g++" && -x "$R/usr/bin/ninja" ]] \
  || die "rootfs needs cmake, g++ and ninja"

# Refuse a different Frame baseline before downloading or clearing output.
# Presence of ECM alone is insufficient: bluez-qt 6.14 needs ECM >= 6.14.
cmake_version() {
  sed -n 's/^set(PACKAGE_VERSION "\([0-9.]*\)").*/\1/p' "$1"
}
[[ "$(cmake_version "$R/usr/lib/cmake/KF6CoreAddons/KF6CoreAddonsConfigVersion.cmake")" == "$KF_VER" ]] \
  || die "KF_VER must match the rootfs KF6CoreAddons version"
[[ "$(cmake_version "$R/usr/lib/cmake/LibKWorkspace/LibKWorkspaceConfigVersion.cmake")" == "$PLASMA_VER" ]] \
  || die "PLASMA_VER must match the rootfs LibKWorkspace version"
ECM_VER="$(cmake_version "$R/usr/share/ECM/cmake/ECMConfigVersion.cmake")"
[[ -n "$ECM_VER" && "$(printf '%s\n' "$KF_VER" "$ECM_VER" | sort -V | head -1)" == "$KF_VER" ]] \
  || die "rootfs needs extra-cmake-modules >= $KF_VER"

# Linux build host: resolve relative paths and symlinks before any cleanup.
OUT="$(realpath -m "$OUT")"
SRC="$(realpath -m "$SRC")"
[[ "$R" != / && "$OUT" != / && "$SRC" != / ]] || die "root paths are not build directories"
disjoint() {
  [[ "$1" != "$2" && "$1" != "$2/"* && "$2" != "$1/"* ]] \
    || die "rootfs, source and output directories must not overlap"
}
disjoint "$R" "$OUT"
disjoint "$R" "$SRC"
disjoint "$SRC" "$OUT"

fetch() {  # fetch NAME URL
  local name=$1 url=$2
  [[ -d "$SRC/$name" ]] && return 0
  mkdir -p "$SRC"
  log "fetching $name"
  curl -fsSL --retry 3 -o "$SRC/$name.tar.xz" "$url"
  tar -C "$SRC" -xJf "$SRC/$name.tar.xz"
  sha256sum "$SRC/$name.tar.xz" > "$SRC/$name.tar.xz.sha256"
}

fetch "bluez-qt-${KF_VER}" "${KDE_MIRROR}/frameworks/${KF_VER%.*}/bluez-qt-${KF_VER}.tar.xz"
fetch "bluedevil-${PLASMA_VER}" "${KDE_MIRROR}/plasma/${PLASMA_VER}/bluedevil-${PLASMA_VER}.tar.xz"
fetch "libkscreen-${PLASMA_VER}" "${KDE_MIRROR}/plasma/${PLASMA_VER}/libkscreen-${PLASMA_VER}.tar.xz"
fetch "kscreen-${PLASMA_VER}" "${KDE_MIRROR}/plasma/${PLASMA_VER}/kscreen-${PLASMA_VER}.tar.xz"

# Do not delete unrelated files in a caller-supplied output directory.
rm -rf "$OUT/stage" "$OUT/build" "$OUT/kde-extras.tar"
mkdir -p "$OUT/stage" "$OUT/build"

run() {
  bwrap --ro-bind "$R" / \
    --dev /dev --proc /proc --tmpfs /run --tmpfs /tmp \
    --dir /tmp/kde-src --bind "$SRC" /tmp/kde-src \
    --dir /tmp/kde-out --bind "$OUT" /tmp/kde-out \
    --unshare-pid --die-with-parent --chdir /tmp/kde-out \
    --setenv PATH /usr/bin \
    --setenv CMAKE_PREFIX_PATH /tmp/kde-out/stage/usr \
    "$@"
}

build() {  # build SOURCE-DIR [cmake args...]
  local s=$1; shift
  log "building $s"
  # No KDocTools in the rootfs, and the handbooks aren't needed.
  sed -i -e 's/\bDocTools\b//' -e '/add_subdirectory *( *doc/d' -e '/kdoctools_install/d' \
    "$SRC/$s/CMakeLists.txt"
  run cmake -S "/tmp/kde-src/$s" -B "/tmp/kde-out/build/$s" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_INSTALL_LIBEXECDIR=lib \
    -DKDE_INSTALL_QTPLUGINDIR=lib/qt6/plugins -DKDE_INSTALL_QMLDIR=lib/qt6/qml \
    -DKDE_INSTALL_SYSTEMDUSERUNITDIR=lib/systemd/user \
    -DBUILD_TESTING=OFF -DBUILD_QCH=OFF "$@"
  run ninja -j"${BUILD_JOBS:-2}" -C "/tmp/kde-out/build/$s"
  run env DESTDIR=/tmp/kde-out/stage ninja -C "/tmp/kde-out/build/$s" install
}

build "bluez-qt-${KF_VER}"
# bluedevil links bluez-qt from the stage, not from the rootfs.
build "bluedevil-${PLASMA_VER}" -DKF6BluezQt_DIR="/tmp/kde-out/stage/usr/lib/cmake/KF6BluezQt"
build "libkscreen-${PLASMA_VER}"
build "kscreen-${PLASMA_VER}" -DKF6Screen_DIR="/tmp/kde-out/stage/usr/lib/cmake/KF6Screen"

# Nothing a running system needs from the headers or CMake files.
rm -rf "$OUT/stage/usr/include" "$OUT/stage/usr/lib/cmake" "$OUT/stage/usr/lib/pkgconfig" \
  "$OUT/stage/usr/mkspecs" "$OUT/stage/usr/lib/qt6/mkspecs"
# Check the runtime consumers, not just the two KCM entry points.
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
  [[ -s "$OUT/stage/$f" ]] || die "missing runtime component: $f"
done
for f in usr/bin/bluedevil-wizard usr/bin/bluedevil-sendfile \
         usr/lib/kscreen_osd_service usr/lib/kf6/kscreen_backend_launcher; do
  [[ -x "$OUT/stage/$f" ]] || die "runtime helper is not executable: $f"
done
# Drain strings completely under pipefail (grep -q can SIGPIPE it and hide a
# match). Check helpers as well as libraries; a read failure must also fail.
find "$OUT/stage" -type f \( -name '*.so*' -o -perm /111 \) \
  -exec strings {} + >"$OUT/runtime-strings.txt"
if grep -E 'GLIBC_2\.([4-9][0-9]|[1-9][0-9]{2,})([^0-9]|$)' "$OUT/runtime-strings.txt" >/dev/null; then
  die "built against a newer glibc than the Frame"
fi
rm -f "$OUT/runtime-strings.txt"
tar -C "$OUT/stage" --owner=0 --group=0 -cf "$OUT/kde-extras.tar" .
log "OK: $OUT/kde-extras.tar ($(tar -tf "$OUT/kde-extras.tar" | grep -vc '/$') files)"
