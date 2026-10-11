#!/bin/bash
# Run the existing local builder from the adjacent external Colima home.
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
workspace=$(dirname "$repo")
export COLIMA_HOME="$workspace/colima"
export LIMA_HOME="$COLIMA_HOME/_lima"
export COLIMA_CACHE_HOME="$COLIMA_HOME/cache"
if [[ ! -f "$COLIMA_HOME/pocket-evo/colima.yaml" ||
      ! -d "$workspace/Steam-OS-ARM-PocketEvo-build" ]]; then
  echo "Attach the Pocket EVO workspace drive with its Colima profile first." >&2
  exit 1
fi
case "${1:-status}" in
  start)
    colima start pocket-evo
    docker --context colima-pocket-evo start pocket-evo-build
    ;;
  stop)
    docker --context colima-pocket-evo stop pocket-evo-build
    colima stop pocket-evo
    ;;
  status)
    colima list
    if colima -p pocket-evo status >/dev/null 2>&1; then
      docker --context colima-pocket-evo ps -a --filter name=pocket-evo-build
    fi
    ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
