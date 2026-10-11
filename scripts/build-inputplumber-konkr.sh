#!/usr/bin/env bash
# Build on ARM64 Linux with glibc <= 2.39, Rust 1.93.1, libiio/udev/clang development files.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CACHE="$ROOT/external-and-mods/InputPlumber"
SRC="${INPUTPLUMBER_BUILD_SRC:-/work/inputplumber-konkr-src}"
OUTPUT="${INPUTPLUMBER_OUTPUT:-$CACHE}"
REF=ea60d873cca17edd1cb655ede26f557108135252
[[ $(uname -m) == aarch64 ]] || { echo 'ARM64 build host required' >&2; exit 1; }
if [[ ! -d "$SRC/.git" ]]; then git clone https://github.com/ShadowBlip/InputPlumber.git "$SRC"; fi
[[ -z $(git -C "$SRC" status --porcelain) ]] || { echo 'Use a clean source checkout' >&2; exit 1; }
git -C "$SRC" checkout --detach "$REF"
git -C "$SRC" apply "$CACHE/0001-bound-ayaneo-haptics-polling.patch"
# Rumble effects stop after their length; Steam's trackpad haptics become motor pulses.
git -C "$SRC" apply "$CACHE/0002-ayaneo-haptics-timed-rumble-and-steam-pulses.patch"
# Manage the uhid "AYN Odin2 IMU" (qcom-sdl-pad --motion-only) as a gyro source.
git -C "$SRC" apply "$CACHE/0003-manage-ayn-odin2-imu-uhid.patch"
# Free evdev FF slots and ID maps before suspend or replacing virtual targets.
git -C "$SRC" apply "$CACHE/0004-reset-force-feedback-on-target-change.patch"
(cd "$SRC" && cargo +1.93.1 build --release --locked -j"${BUILD_JOBS:-4}")
mkdir -p "$OUTPUT"
install -m755 "$SRC/target/release/inputplumber" "$OUTPUT/inputplumber-0.81.0-konkr"
(cd "$OUTPUT" && sha256sum inputplumber-0.81.0-konkr > inputplumber-0.81.0-konkr.sha256)
echo 'Verify this binary against the target rootfs before release.'
