#!/usr/bin/env bash
# Run inside the native Pocket EVO builder; isolate its output/cache by recipe.
set -euo pipefail
export WORK=/work/kernel-pocketevo ROCKNIX_DIR=/work/rocknix FRAME_FW_DIR=/work/frame-fw
export JOBS=${JOBS:-6}
unset LOCALVERSION DTBS_OVERRIDE
exec bash /src/external-and-mods/kernel-pocketevo/build.sh "$@"
