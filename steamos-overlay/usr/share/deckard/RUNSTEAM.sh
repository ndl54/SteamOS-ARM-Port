#!/bin/bash
# Handheld SM8550 launcher. Do not pass -deckard / -vrgamepadui: those switch
# the client beta to the internal Steam Frame build and wait on SteamVR.

set -euo pipefail
STEAMROOT="$( cd -- "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

IS_SIDELOAD=0
SIDELOADED_STEAMROOT="${HOME}/devkit-game/steam"
if [ "${STEAMROOT}" == "${SIDELOADED_STEAMROOT}" ]; then
  echo "Running sideloaded Steam client in ${STEAMROOT}"
  IS_SIDELOAD=1
  export SUPPRESS_STEAM_OVERLAY=1
fi

STEAM_RT_ARM64=steamrtarm64
STEAM_SDK_ARM64=linuxarm64

if [[ ! -d "${STEAMROOT}/${STEAM_RT_ARM64}" ]]; then
  if [[ -d "${STEAMROOT}/linuxarm64" ]]; then
    STEAM_RT_ARM64="linuxarm64"
  fi
fi

if [[ ! -d "${STEAMROOT}/${STEAM_SDK_ARM64}" ]]; then
  if [[ -d "${STEAMROOT}/steamrtarm64" ]]; then
    STEAM_SDK_ARM64="steamrtarm64"
  fi
fi

export LD_LIBRARY_PATH="${STEAMROOT}/${STEAM_RT_ARM64}"
export SteamDeck="${SteamDeck:-1}"
export QT_QPA_PLATFORM=xcb
export _STEAM_SETENV_MANAGER=1
export DISPLAY="${DISPLAY:-:0}"
if [[ -z "${GAMESCOPE_WAYLAND_DISPLAY:-}" ]]; then
  if [[ -S "${XDG_RUNTIME_DIR:-/run/user/1000}/gamescope-0" ]]; then
    export GAMESCOPE_WAYLAND_DISPLAY=gamescope-0
  fi
fi
export GAMESCOPE_WAYLAND_DISPLAY="${GAMESCOPE_WAYLAND_DISPLAY:-gamescope-0}"
unset WAYLAND_DISPLAY XDG_SESSION_TYPE || true
for _i in $(seq 1 50); do
  [[ -S /tmp/.X11-unix/X0 ]] && break
  sleep 0.1
done
# Force-off leaves .crash; Steam then opens -child-update-ui (the wheel)
# and logs "Looks like steam didn't shutdown cleanly".
rm -f "${STEAMROOT}/.crash" "${STEAMROOT}/steam.pid" 2>/dev/null || true
# Client self-updates are blocked by default (x86 CDN builds break the handheld).
# Opt in with `touch ${STEAMROOT}/.allow-client-updates` (or
# STEAM_ALLOW_CLIENT_UPDATES=1) to follow the selected client beta channel,
# e.g. the arm64 build shared with the Steam Frame.
ALLOW_CLIENT_UPDATES=0
if [[ -e "${STEAMROOT}/.allow-client-updates" || "${STEAM_ALLOW_CLIENT_UPDATES:-0}" == "1" ]]; then
  ALLOW_CLIENT_UPDATES=1
fi
# Preserve custom settings; migrate only the exact five shipped defaults.
# Failure is fatal here: do not silently launch with a stale update policy.
python3 - "${STEAMROOT}" "${STEAM_RT_ARM64}" "${ALLOW_CLIENT_UPDATES}" <<'STEAM_CFG'
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

root, runtime, allow = sys.argv[1:]
defaults = [b'BootStrapperInhibitAll=enable',
            b'BootStrapperForceSelfUpdate=disable',
            b'BootStrapperInhibitClientChecksum=enable',
            b'BootStrapperInhibitBootstrapperChecksum=enable',
            b'BootStrapperInhibitUpdateOnLaunch=enable']
for path in (Path(root) / 'steam.cfg', Path(root) / runtime / 'steam.cfg'):
    if not path.parent.is_dir():
        continue
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SystemExit(f'RUNSTEAM: refusing non-regular config {path}')
    original = path.read_bytes() if path.exists() else b''
    lines = [line for line in original.splitlines(keepends=True)
             if line.rstrip(b'\r\n') not in defaults]
    if allow != '1':
        # Explicit values (including custom bootstrap choices) are user-owned.
        for default in defaults:
            key = default.split(b'=', 1)[0]
            if not any(re.match(rb'^\s*' + key + rb'\s*=', line, re.I) for line in lines):
                if lines and not lines[-1].endswith(b'\n'):
                    lines[-1] += b'\n'
                lines.append(default + b'\n')
    data = b''.join(lines)
    if data == original:
        continue
    fd, tmp = tempfile.mkstemp(prefix='.steam.cfg.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            os.fchmod(out.fileno(), stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
STEAM_CFG
# Version 0 / "no bootstrapper found" keeps Gamepad UI on the update spinner.
if [[ ! -s "${STEAMROOT}/steam.inf" ]]; then
  ver=1788652215
  [[ -r "${STEAMROOT}/.odin-handheld-client" ]] \
    && ver="$(awk 'NR==2 && /^[0-9]+$/{print; exit}' "${STEAMROOT}/.odin-handheld-client")"
  printf 'ClientVersion=%s\n' "${ver:-1788652215}" >"${STEAMROOT}/steam.inf"
  cp -f "${STEAMROOT}/steam.inf" "${STEAMROOT}/steamrtarm64/steam.inf" 2>/dev/null || true
fi
# Force-off leaves Chrome singleton locks + a half-written htmlcache.
# Then index.html paints and never pulls libraries.js (no Gamepad window).
htmlcache="${STEAMROOT}/config/htmlcache"
is_odin3=0
if grep -aqE "ayn,odin3|qcom,sm8750" /sys/firmware/devicetree/base/compatible 2>/dev/null; then
  is_odin3=1
fi
if [[ "$is_odin3" -eq 1 ]]; then
  ram_cache="/tmp/steam-htmlcache-${USER:-steamos}"
  mkdir -p "${ram_cache}" 2>/dev/null || true
  if [[ ! -L "${htmlcache}" ]]; then
    rm -rf "${htmlcache}" 2>/dev/null || true
    ln -sfn "${ram_cache}" "${htmlcache}" 2>/dev/null || true
  fi

  # Odin 3 baseline: ensure config.vdf has controller mapping and UI scale factor
  cfg="${STEAMROOT}/config/config.vdf"
  if [[ ! -f "$cfg" ]]; then
    mkdir -p "${STEAMROOT}/config"
    cat <<'VDF' >"$cfg"
"InstallConfigStore"
{
	"SDL_GamepadBind"		"03000000202000000130000001000000,AYN Odin3 Gamepad,crc:95bb,platform:Linux,a:b0,b:b1,x:b3,y:b2,dpleft:b13,dpright:b14,dpup:b11,dpdown:b12,leftx:a0,lefty:a1,leftstick:b9,rightx:a3,righty:a4,rightstick:b10,leftshoulder:b4,lefttrigger:a2,rightshoulder:b5,righttrigger:a5,back:b6,start:b7,guide:b8,misc1:b15,steam:2,"
	"UI"
	{
		"display"
		{
			"Current"
			{
				"MinScaleFactor"		"0.711512446403503418"
				"MaxScaleFactor"		"3.40971922874450684"
				"IsExternalDisplay"		"1"
				"name"		"External: gamescope 6\"|||Windowed"
				"AutoScaleFactor"		"2.80762958526611328"
				"ScaleFactor"		"2.38840627670288086"
			}
			"External: gamescope 6\"|||Windowed"
			{
				"ScaleFactor"		"2.38840627670288086"
			}
		}
	}
	"SteamOS"
	{
		"WifiForceWPASupplicant"		"1"
	}
}
VDF
  elif ! grep -q 'External: gamescope 6' "$cfg" 2>/dev/null; then
    python3 -c '
import sys
p = sys.argv[1]
try:
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        c = f.read()
    if "\"UI\"" not in c and "External: gamescope 6" not in c:
        block = """\t"UI"
\t{
\t\t"display"
\t\t{
\t\t\t"Current"
\t\t\t{
\t\t\t\t"MinScaleFactor"\t\t"0.711512446403503418"
\t\t\t\t"MaxScaleFactor"\t\t"3.40971922874450684"
\t\t\t\t"IsExternalDisplay"\t\t"1"
\t\t\t\t"name"\t\t"External: gamescope 6\\\"|||Windowed"
\t\t\t\t"AutoScaleFactor"\t\t"2.80762958526611328"
\t\t\t\t"ScaleFactor"\t\t"2.38840627670288086"
\t\t\t}
\t\t\t"External: gamescope 6\\\"|||Windowed"
\t\t\t{
\t\t\t\t"ScaleFactor"\t\t"2.38840627670288086"
\t\t\t}
\t\t}
\t}\n"""
        idx = c.rfind("}")
        if idx != -1:
            c = c[:idx] + block + c[idx:]
            with open(p, "w", encoding="utf-8") as f:
                f.write(c)
except Exception:
    pass
' "$cfg" 2>/dev/null || true
  fi
fi
if [[ -L "${htmlcache}/SingletonLock" || -e "${htmlcache}/SingletonLock" ]]; then
  rm -f "${htmlcache}/SingletonLock" "${htmlcache}/SingletonCookie" \
        "${htmlcache}/SingletonSocket" 2>/dev/null || true
fi
# ResourceHandler serves on-disk steamui/ when present. 0-byte stubs or a
# missing tree produce a blank steamloopback page (no libraries.js).
# The Frame tarball client never finishes the library. Prefer the handheld
# ARM client extracted by apply-overlays / install-steam-client-arm64.
steam_tar=/usr/lib/steam/steam.tar.zst
if [[ ! -e "${STEAMROOT}/.odin-handheld-client" && -f "$steam_tar" ]]; then
  if [[ ! -s "${STEAMROOT}/steamui/index.html" ]] \
     || ! grep -q 'libraries~' "${STEAMROOT}/steamui/index.html" 2>/dev/null; then
    rm -rf "${STEAMROOT}/steamui"
    tar --zstd -xf "$steam_tar" -C "${STEAMROOT}" ./steamui 2>/dev/null || true
  fi
fi
if [[ -x /usr/lib/steamos/sm8550-patch-steamui ]]; then
  /usr/lib/steamos/sm8550-patch-steamui "${STEAMROOT}/steamui" >/dev/null 2>&1 || true
fi
# Frame tarball leaves linuxarm64/steamclient.so as 0 bytes. webhelper
# dlmopens that path and Gamepad UI never creates the BPM window.
if [[ -d "${STEAMROOT}/linuxarm64" && -d "${STEAMROOT}/steamrtarm64" ]]; then
  for _lib in steamclient.so crashhandler.so steam-launch-wrapper; do
    _src="${STEAMROOT}/steamrtarm64/${_lib}"
    _dst="${STEAMROOT}/linuxarm64/${_lib}"
    if [[ -s "$_src" && ! -s "$_dst" ]]; then
      cp -f "$_src" "$_dst" 2>/dev/null || true
    fi
  done
  unset _lib _src _dst
fi
# PyroWave is an optional x86-64 Remote Play route, independent of game FEX.
# Only replace a real AArch64 client or our own wrapper, with an atomic backup
# first. Client updates can publish a new native binary between launches.
python3 - "${STEAMROOT}" "${STEAM_RT_ARM64}" <<'PYROWAVE_SETUP' || echo "RUNSTEAM: PyroWave setup failed; inspect streaming_client and its .arm64 backup" >&2
import fcntl
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

root = Path(sys.argv[1])
client = root / sys.argv[2] / 'streaming_client'
backup = client.with_name(client.name + '.arm64')
x86 = root / 'steamrt64/streaming_client'
marker = b'# PYROWAVE_BOX64_WRAPPER'

def regular(path):
    return path.is_file() and not path.is_symlink()

def elf(path, machine):
    if not regular(path) or not os.access(path, os.X_OK):
        return False
    with path.open('rb') as stream:
        header = stream.read(20)
    return (len(header) == 20 and header[:6] == b'\x7fELF\x02\x01'
            and int.from_bytes(header[18:20], 'little') == machine)

def owned(path):
    if not regular(path):
        return False
    with path.open('rb') as stream:
        return (stream.readline().rstrip() == b'#!/bin/sh'
                and stream.readline().startswith(marker))

def publish(path, data, mode):
    if path.is_symlink() or (path.exists() and not regular(path)):
        raise RuntimeError(f'refusing non-regular destination {path}')
    fd, tmp = tempfile.mkstemp(prefix='.streaming-client.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            os.fchmod(out.fileno(), mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

wrapper = b'''#!/bin/sh
# PYROWAVE_BOX64_WRAPPER (managed by RUNSTEAM.sh)
S=$(CDPATH= cd -P -- "$(dirname -- "$0")" && cd -P .. && pwd -P) || exit 1
native="$0.arm64"
# A removed opt-in or disappearing prerequisite restores routing immediately.
box=$(command -v box64) || box=
if [ -z "$box" ] && [ -x /usr/local/bin/box64 ]; then box=/usr/local/bin/box64; fi
if [ ! -e "$S/.pyrowave-box64" ] || [ -z "$box" ] || [ ! -x "$S/steamrt64/streaming_client" ]; then
    exec "$native" "$@"
fi
mkdir -p "$S/logs" || exit 1
# Native Steam/overlay preload libraries must not enter the x86 client loader.
unset LD_PRELOAD
export BOX64_EMULATED_LIBS="libSDL3_ttf.so.0${BOX64_EMULATED_LIBS:+:$BOX64_EMULATED_LIBS}"
export BOX64_LD_LIBRARY_PATH="$S/steamrt64:$S/ubuntu12_64:$S/linux64${BOX64_LD_LIBRARY_PATH:+:$BOX64_LD_LIBRARY_PATH}"
exec "$box" "$S/steamrt64/streaming_client" "$@" >"$S/logs/streaming_client_box64.log" 2>&1
'''
# Serialize cooperating launcher setup only; Steam's updater does not use this lock.
with (root / '.pyrowave-setup.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    enabled = ((root / '.pyrowave-box64').exists() and elf(x86, 62)
               and (shutil.which('box64') or os.access('/usr/local/bin/box64', os.X_OK)))
    if enabled:
        if elf(client, 183):
            publish(backup, client.read_bytes(), stat.S_IMODE(client.stat().st_mode))
        elif not owned(client):
            raise RuntimeError('native client missing or custom/unsupported streaming_client; left unchanged')
        if not elf(backup, 183):
            raise RuntimeError('no valid AArch64 backup; wrapper not changed')
        publish(client, wrapper, 0o755)
    elif owned(client):
        if not elf(backup, 183):
            raise RuntimeError('cannot restore wrapper without a valid AArch64 backup')
        publish(client, backup.read_bytes(), stat.S_IMODE(backup.stat().st_mode))
PYROWAVE_SETUP
echo "RUNSTEAM: DISPLAY=${DISPLAY} GAMESCOPE_WAYLAND_DISPLAY=${GAMESCOPE_WAYLAND_DISPLAY} QT_QPA_PLATFORM=${QT_QPA_PLATFORM}"

if [[ "$is_odin3" -eq 1 && -f /etc/sdl2/qcom-gamecontrollerdb.txt ]]; then
  export SDL_GAMECONTROLLERCONFIG_FILE=/etc/sdl2/qcom-gamecontrollerdb.txt
  export SDL_GAMECONTROLLERCONFIG="$(grep -v '^#' /etc/sdl2/qcom-gamecontrollerdb.txt | tr '\n' ',' 2>/dev/null || true)"
fi

function ln_for_real()
{
  if [[ -d "${2}" ]]; then
    rm -rf "${2}"
  fi
  ln -sTfn "${1}" "${2}"
}

mkdir -p ~/.steam
if [[ "${IS_SIDELOAD}" == "0" ]]; then
  ln_for_real "${STEAMROOT}" ~/.steam/steam
else
  ln_for_real ~/.local/share/Steam ~/.steam/steam
fi
ln_for_real "${STEAMROOT}" ~/.steam/root
ln_for_real "${STEAMROOT}/linux32" ~/.steam/sdk32
ln_for_real "${STEAMROOT}/linux64" ~/.steam/sdk64
ln_for_real "${STEAMROOT}/${STEAM_SDK_ARM64}" ~/.steam/sdkarm64
ln_for_real "${STEAMROOT}/${STEAM_RT_ARM64}" ~/.steam/binarm64
ln_for_real "${STEAMROOT}/ubuntu12_32" ~/.steam/bin32
ln_for_real "${STEAMROOT}/ubuntu12_64" ~/.steam/bin64

export STEAM_RUNTIME="$STEAMROOT/ubuntu12_32/steam-runtime"
if [ -f $STEAMROOT/steamapps/common/FEX-Emu/fex-compat-tool ]; then
  export STEAM_RUNTIME_LIBRARY_PATH=$($STEAMROOT/steamapps/common/FEX-Emu/fex-compat-tool run -- $STEAMROOT/ubuntu12_32/steam-runtime/run.sh --print-steam-runtime-library-paths)
  echo "setting STEAM_RUNTIME_LIBRARY_PATH via FEX-Emu: ${STEAM_RUNTIME_LIBRARY_PATH}"
else
  export STEAM_RUNTIME_LIBRARY_PATH=$STEAM_RUNTIME/pinned_libs_32:$STEAM_RUNTIME/pinned_libs_64:/usr/local/lib/i386-linux-gnu:/lib/i386-linux-gnu:/usr/local/lib:/usr/local/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/lib:$STEAM_RUNTIME/lib/i386-linux-gnu:$STEAM_RUNTIME/usr/lib/i386-linux-gnu:$STEAM_RUNTIME/lib/x86_64-linux-gnu:$STEAM_RUNTIME/usr/lib/x86_64-linux-gnu:$STEAM_RUNTIME/lib:$STEAM_RUNTIME/usr/lib
  echo "setting STEAM_RUNTIME_LIBRARY_PATH copied from legacy LDLP: ${STEAM_RUNTIME_LIBRARY_PATH}"
fi

if [[ "${IS_SIDELOAD}" == "0" ]]; then
  STEAM_ARGS=(
    -cef-enable-debugging
    -gamepadui
    -steamos3
    -steampal
    -steamdeck
    -noverifyfiles
    -noshaders
    -inhibitbootstrap
    -nobootstrapperupdate
    ${STEAM_EXTRA_ARGS:-}
  )
  if [[ "${ALLOW_CLIENT_UPDATES}" == "1" ]]; then
    _kept=()
    for _a in "${STEAM_ARGS[@]}"; do
      [[ "$_a" == -inhibitbootstrap || "$_a" == -nobootstrapperupdate ]] || _kept+=("$_a")
    done
    STEAM_ARGS=("${_kept[@]}")
  fi
else
  SIDELOADED_CMDLINE_ARGS_FILE="${HOME}/devkit-game/steamdeckard-argv.json"
  read -ra STEAM_ARGS <<< "$(jq -r '.[0]' "${SIDELOADED_CMDLINE_ARGS_FILE}")"
fi

STEAM_COMMAND=(
    "${STEAMROOT}/${STEAM_RT_ARM64}/steam" "${STEAM_ARGS[@]}"
)

if [[ "${IS_SIDELOAD}" == "1" ]]; then
  SIDELOADED_SETTINGS_FILE="${HOME}/devkit-game/steamdeckard-settings.json"
  if [[ "$(jq -r '.gdbserver // "0"' "${SIDELOADED_SETTINGS_FILE}")" == "1" ]]; then
    STEAM_COMMAND=(
      gdbserver 127.0.0.1:2345 "${STEAM_COMMAND[@]}"
    )
  fi
fi

cd "${STEAMROOT}"
mkdir -p "${HOME}/.local/share/Steam/logs"
# Steam refuses LD_PRELOAD (unsafe unsetenv) and aborts its own startup UI.
unset LD_PRELOAD || true

exec "${STEAM_COMMAND[@]}" >"${HOME}/.local/share/Steam/logs/steam_output.log" 2>&1
