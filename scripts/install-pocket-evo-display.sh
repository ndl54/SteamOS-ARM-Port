#!/bin/bash
# Install the already-tested Gamescope build into an offline rootfs.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
R=${1:?usage: install-pocket-evo-display.sh ROOTFS GAMESCOPE_BUILD}
GSBUILD=${2:?Gamescope build directory required}
# Bind the selected build to this run's source/output manifest, not an old
# historical artifact hash. The repack exports this manifest after fresh builds.
PROVENANCE=${COMPONENT_MANIFEST:?fresh component manifest required}
python3 "$ROOT/scripts/pocket-evo-component-manifest.py" verify "$PROVENANCE"
python3 - "$GSBUILD" "$PROVENANCE" <<'PYCODE'
import json,sys
from pathlib import Path
build=Path(sys.argv[1]).resolve()
outputs=json.loads(Path(sys.argv[2]).read_text())['outputs_sha256']
for name in ('src/gamescope','src/gamescopectl','src/gamescopereaper','src/gamescopestream','layer/libVkLayer_FROG_gamescope_wsi_aarch64.so'):
    assert str(build/name) in outputs, 'Gamescope path absent from manifest: '+name
print('Selected Gamescope output is covered by fresh component manifest')
PYCODE

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
