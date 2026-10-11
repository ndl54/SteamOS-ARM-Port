#!/bin/bash
# Install the already-tested Gamescope build into an offline rootfs.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
R=${1:?usage: install-pocket-evo-display.sh ROOTFS GAMESCOPE_BUILD}
GSBUILD=${2:?Gamescope build directory required}
# Refuse a stale/incomplete binary before modifying the rootfs.
python3 - "$ROOT" "$GSBUILD" <<'PY'
import hashlib, json, sys
from pathlib import Path
repo, build = map(Path, sys.argv[1:])
files = json.loads((repo/'docs/audit/pocket-evo-build-results.json').read_text())['gamescope_followup']['files']
for name, expected in files.items():
    p = build / Path(name).relative_to('build')
    assert hashlib.sha256(p.read_bytes()).hexdigest() == expected['sha256'], p
print('Verified final Gamescope build hashes')
PY
for prefix in usr usr/local; do
  for b in gamescope gamescopectl gamescopereaper gamescopestream; do
    install -Dm755 "$GSBUILD/src/$b" "$R/$prefix/bin/$b"
  done
  install -Dm755 "$GSBUILD/layer/libVkLayer_FROG_gamescope_wsi_aarch64.so" "$R/$prefix/lib/libVkLayer_FROG_gamescope_wsi_aarch64.so"
  mkdir -p "$R/$prefix/share/gamescope"
  # Match the existing image pipeline: replace obsolete default profiles.
  for section in scripts looks; do
    rsync -a --delete "$ROOT/external-and-mods/gamescope/$section/" "$R/$prefix/share/gamescope/$section/"
  done
  setcap cap_sys_nice=eip "$R/$prefix/bin/gamescope"
done
mkdir -p "$R/usr/share/vulkan/implicit_layer.d"
sed 's|/usr/local/lib/|/usr/lib/|' "$GSBUILD/layer/VkLayer_FROG_gamescope_wsi.aarch64.json" > "$R/usr/share/vulkan/implicit_layer.d/VkLayer_FROG_gamescope_wsi.aarch64.json"
install -Dm644 "$ROOT/external-and-mods/gamescope/scripts/udev/60-gamescope-backlight.rules" "$R/usr/lib/udev/rules.d/60-gamescope-backlight.rules"
