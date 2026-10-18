#!/usr/bin/env bash
# Build mangoapp (Steam's performance overlay) inside the SteamOS rootfs, so
# it links against SteamOS's glibc: MangoHud v0.8.4 + the patches in
# external-and-mods/MangoHud-qualcomm (GPU load, clock and VRAM on Adreno).
#
# Usage: build-mangohud-in-rootfs.sh <rootfs> [build-dir]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
R="$(cd "${1:?rootfs}" && pwd)"
WORKDIR="${STEAMOS_WORK:-/work}"
BUILD="${2:-${WORKDIR}/mangohud-build}"
TAG=v0.8.4
REF=992103e4fb744897826de04ea00a2f71e7018214
log() { printf '==> [mangohud] %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command -v bwrap >/dev/null || die "bwrap required"
[[ -x "$R/usr/bin/gcc" && -x "$R/usr/bin/python3" ]] || die "rootfs needs gcc + python3"

mkdir -p "$WORKDIR"
T=$(mktemp -d "$WORKDIR/mangohud-source.XXXXXX")
printf '%s\n' "$REF" > "$T/source-ref"
log "MangoHud $TAG"
curl -fL --retry 3 "https://github.com/flightlessmango/MangoHud/archive/${REF}.tar.gz" -o "$T/source.tar.gz"
sha256sum "$T/source.tar.gz" > "$T/source.sha256"
tar -xzf "$T/source.tar.gz" -C "$T"
mv "$T/MangoHud-${REF}" "$T/src"
for p in "$ROOT/external-and-mods/MangoHud-qualcomm/patches/"*.patch; do
  log "patch $(basename "$p")"
  patch -d "$T/src" -p1 --quiet < "$p"
done
# v0.8.4 wants a newer meson than the rootfs has: a private copy for the build.
bwrap --ro-bind "$R" / --dev /dev --proc /proc --tmpfs /tmp \
  --dir /tmp/meson --bind "$T" /tmp/meson --ro-bind /etc/resolv.conf /etc/resolv.conf \
  /usr/bin/python3 -m pip install --disable-pip-version-check --no-cache-dir --target /tmp/meson/pymeson "meson==1.8.2"
bwrap --ro-bind "$R" / --dev /dev --proc /proc --tmpfs /tmp --tmpfs /t --bind "$T" /t/mangohud --ro-bind /etc/resolv.conf /etc/resolv.conf \
  bash -c 'set -e; export PYTHONPATH=/t/mangohud/pymeson
    cd /t/mangohud/src
    rm -rf /t/mangohud/build
    python3 -m mesonbuild.mesonmain setup /t/mangohud/build --buildtype=release --prefix=/usr \
      -Dmangoapp=true -Dmangohudctl=false -Dwith_xnvctrl=disabled -Dwith_nvml=disabled \
      -Dtests=disabled -Dinclude_doc=false -Dmangoplot=disabled >/dev/null
    ninja -j"${BUILD_JOBS:-2}" -C /t/mangohud/build src/mangoapp'
mkdir -p "$BUILD"
install -m0755 "$T/build/src/mangoapp" "$BUILD/mangoapp"
cp "$T/source-ref" "$T/source.sha256" "$BUILD/"
printf '%s\n' "$T" > "$BUILD/source-directory"
log "OK: $BUILD/mangoapp"
