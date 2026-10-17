#!/bin/bash
# Lenovo Legion Y700 Gen 3 (TB321FU) support in the 8 Gen 3 rootfs.
#
#   install-tb321fu.sh ROOTFS
#
# Firmware and the audio profile, kept out of what the Pocket FIT and Pocket
# S2 use from the same rootfs:
#  - the tablet's own files go to its own paths (qcom/sm8650/lenovo/tb321fu,
#    qca/hmtnv20_Kirby_*, the Qualcomm/sm8650/TB321FU UCM)
#  - its Wi-Fi firmware and board data replace the shared WCN7850 files, so
#    they go to /usr/lib/firmware/steamos-arm/tb321fu, which only the
#    tablet's cmdline puts first in the search (firmware_class.path)
#  - settings no other device should get are installed by units gated on
#    its device tree
# Downloads are cached in ${CACHE:-/work/cache/tb321fu-boot}.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${HERE}/../external-and-mods/tb321fu-boot/release.env"
R="${1:?rootfs}"
CACHE="${CACHE:-/work/cache/tb321fu-boot}"
log() { echo "[tb321fu] $*"; }
die() { echo "[tb321fu] ERROR: $*" >&2; exit 1; }
mkdir -p "$CACHE"

fetch() {  # fetch URL FILE [SHA256]
  [[ -s "$CACHE/$2" ]] || { curl -fsSL --retry 3 -o "$CACHE/$2.part" "$1"; mv -f "$CACHE/$2.part" "$CACHE/$2"; }
  [[ -z "${3:-}" ]] || echo "$3  $CACHE/$2" | sha256sum -c --quiet || die "hash mismatch: $2"
}

# Firmware: unpack, check the pinned SHA256SUMS, then every file against it.
fetch "$TB321FU_FW_URL" tb321fu-firmware.tar.gz
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
tar -C "$W" -xzf "$CACHE/tb321fu-firmware.tar.gz"
FW="$(echo "$W"/firmware-lenovo-tb321fu-*)"
echo "$TB321FU_FW_SUMS_SHA256  $FW/SHA256SUMS" | sha256sum -c --quiet || die "firmware SHA256SUMS changed"
(cd "$FW" && sha256sum -c --quiet SHA256SUMS) || die "firmware files don't match SHA256SUMS"

F="$R/usr/lib/firmware"
mkdir -p "$F/qcom/sm8650/lenovo" "$F/steamos-arm/tb321fu/ath12k/WCN7850"
rm -rf "$F/qcom/sm8650/lenovo/tb321fu"
cp -a "$FW/usr/lib/firmware/qcom/sm8650/lenovo/tb321fu" "$F/qcom/sm8650/lenovo/"
cp -a "$FW/usr/lib/firmware/qcom/sm8650/Lenovo-Y700-TB321FU-tplg.bin" "$F/qcom/sm8650/"
cp -a "$FW/usr/lib/firmware/aw882xx_acf.bin" "$FW/usr/lib/firmware/haptic_click.bin" \
  "$FW/usr/lib/firmware/haptic_ram.bin" "$F/"
rm -rf "$F/steamos-arm/tb321fu/ath12k/WCN7850/hw2.0"
cp -a "$FW/usr/lib/firmware/updates/ath12k/WCN7850/hw2.0" "$F/steamos-arm/tb321fu/ath12k/WCN7850/"

# GUF296's packages: Bluetooth NVM, CSOT touch firmware.
fetch "$TB321FU_DEBS_URL" tb321fu-debs.tar.gz "$TB321FU_DEBS_SHA256"
mkdir -p "$W/debs" "$W/ov"
tar -C "$W/debs" -xzf "$CACHE/tb321fu-debs.tar.gz"
deb="$(echo "$W"/debs/y700-daily-rootfs-overlay_*_arm64.deb)"
[[ -f "$deb" ]] || die "no rootfs overlay package in the device packages"
(cd "$W/debs" && ar x "$deb" data.tar.xz)
tar -C "$W/ov" -xJf "$W/debs/data.tar.xz" ./usr/lib/firmware
O="$W/ov/usr/lib/firmware"
cp -a "$O/qca/hmtnv20_Kirby_prc.bin" "$O/qca/hmtnv20_Kirby_row.bin" "$F/qca/"
# The Kirby NVM only loads after the patch it was released with
# (BTFW.HAMILTON.2.0.1-00355); with the newer shared hmtbtfw20.tlv the
# controller rejects it (-52) and Bluetooth never comes up. The pair goes
# to the tablet's own firmware path, searched first only on the tablet.
mkdir -p "$F/steamos-arm/tb321fu/qca"
cp -a "$O/qca/hmtbtfw20.tlv" "$O/qca/hmtnv20_Kirby_prc.bin" "$O/qca/hmtnv20_Kirby_row.bin" \
  "$F/steamos-arm/tb321fu/qca/"
cp -a "$O/qcom/sm8650/lenovo/tb321fu/novatek_ts_csot_fw.bin" \
  "$O/qcom/sm8650/lenovo/tb321fu/novatek_ts_csot_mp.bin" "$F/qcom/sm8650/lenovo/tb321fu/"

# Audio profile: from the tree the kernel is built from (same commit), whose
# controls it uses (aw882xx_rx_switch, aw_dev_N_switch, ...). GUF296's
# profile was written for his kernel's controls and routes nothing on this one.
port_archive="tb321fu-port-${TB321FU_PORT_SHA256}.tar.gz"
fetch "$TB321FU_PORT_URL" "$port_archive" "$TB321FU_PORT_SHA256"
mkdir -p "$W/port"
tar -C "$W/port" -xzf "$CACHE/$port_archive" --strip-components=1 --wildcards '*/system_files/usr/share/alsa/ucm2/*'
A="$W/port/system_files/usr/share/alsa/ucm2"
[[ -f "$A/Qualcomm/sm8650/TB321FU/HiFi.conf" ]] || die "no TB321FU audio profile in the kernel's source tree"
U="$R/usr/share/alsa/ucm2"
rm -rf "$U/LenovoY700TB321" "$U/Qualcomm/sm8650/TB321FU"
rm -f "$U/conf.d/snd_soc_sc8280xp/Lenovo-Y700-TB321FU.conf" "$U/conf.d/snd_soc_sc8280xp/Lenovo-QRD-2.0.conf"
mkdir -p "$U/Qualcomm/sm8650" "$U/conf.d/sm8650"
cp -a "$A/Qualcomm/sm8650/TB321FU" "$U/Qualcomm/sm8650/"
# Our HiFi verb over the tree's: speakers on PCM 0 through Secondary TDM,
# the route heard on a tablet (the tree's PCM 1 route stayed silent).
install -m0644 "${HERE}/../external-and-mods/tb321fu-boot/ucm/HiFi.conf" "$U/Qualcomm/sm8650/TB321FU/HiFi.conf"
# Some Lenovo firmware names the card Lenovo-QRD-2.0.
for n in Lenovo-Y700-TB321FU Lenovo-QRD-2.0; do
  install -m0644 "$A/conf.d/sm8650/$n.conf" "$U/conf.d/sm8650/$n.conf"
done
# The QRD alias can have a different ALSA card ID. Resolve every PCM/CTL
# against the card that opened this profile, not a hard-coded Y700 ID.
sed -i 's/LenovoY700TB321/${CardId}/g' "$U/Qualcomm/sm8650/TB321FU/HiFi.conf"
# Check every direct include, including capture and disable sequences.
while IFS= read -r f; do
  [[ -f "$U$f" ]] || die "the rootfs's alsa-ucm-conf has no $f, which the profile includes"
done < <(sed -n 's/^[[:space:]]*\(Include\..*\.\)\{0,1\}File "\([^" ]*\)".*/\2/p' \
  "$U/Qualcomm/sm8650/TB321FU/"*.conf "$U/conf.d/sm8650/Lenovo-Y700-TB321FU.conf" | sort -u)

# The ADSP takes at most 65280-byte buffers in 2-8 periods for this card;
# PipeWire's default request fails (EINVAL) and nothing plays. The Pocket
# FIT's rules in /etc (53-konkr-audio, 54-konkr-quantum) match every
# platform-sound card: they set 960-frame periods
# and ask for a "HiFi (Headphones, Speaker)" profile this card doesn't have
# (speakers and headphones share PCM 0 and exclude each other, and the mics
# are part of every profile). Fragments sort within each directory, and /etc
# loads after /usr/share regardless of name. The tablet's setup unit installs
# this into /etc before the session starts; there 90 sorts after 53/54.
# Match both card and node properties exactly. Prefer speakers with the
# internal mic: the preferred-profile hook matches names without checking
# jack availability, so a headphones-first list can select a silent output.
rm -f "$R/usr/share/wireplumber/wireplumber.conf.d/51-lenovo-tb321fu-alsa.conf" \
  "$R/usr/share/wireplumber/wireplumber.conf.d/90-lenovo-tb321fu-alsa.conf"
install -Dm0644 /dev/stdin "$R/usr/share/steamos-arm/tb321fu/90-lenovo-tb321fu-alsa.conf" <<'CONF'
# Lenovo Legion Y700 Gen 3: its own profile order and the buffer sizes the
# ADSP accepts for its card (after the Pocket FIT's 53/54 rules).
monitor.alsa.rules = [
  {
    matches = [
      { alsa.card_name = "Lenovo-Y700-TB321FU" } { alsa.card_name = "Lenovo-QRD-2.0" }
      { api.alsa.card.name = "Lenovo-Y700-TB321FU" } { api.alsa.card.name = "Lenovo-QRD-2.0" }
    ]
    actions = {
      update-props = {
        api.acp.auto-profile = true
        api.acp.auto-port = true
        device.profile = "HiFi (Mic1, Speaker)"
        api.alsa.period-size = 1024
        api.alsa.period-num = 4
        api.alsa.headroom = 0
        api.alsa.disable-tsched = false
        node.force-quantum = 1024
      }
    }
  }
]
device.profile.priority.rules = [
  {
    matches = [
      { alsa.card_name = "Lenovo-Y700-TB321FU" } { alsa.card_name = "Lenovo-QRD-2.0" }
      { api.alsa.card.name = "Lenovo-Y700-TB321FU" } { api.alsa.card.name = "Lenovo-QRD-2.0" }
    ]
    actions = {
      update-props = {
        priorities = [
          "HiFi (Mic1, Speaker)"
          "HiFi (Headset, Speaker)"
          "HiFi (Headphones, Headset)"
          "HiFi (Headphones, Mic1)"
          "HiFi"
          "pro-audio"
        ]
      }
    }
  }
]
CONF

# Desktop Mode: the panel's two halves are 800 px wide, so the DPU's inline
# rotator takes the rotation and leaves a line at the seam; KWin rotates in
# the compositor instead (Game Mode already uses gamescope's shader).
install -Dm0755 /dev/stdin "$R/etc/xdg/plasma-workspace/env/steamos-arm-tablet-kwin.sh" <<'ENV'
#!/bin/sh
# Lenovo Legion Y700 Gen 3: rotate in the compositor (see install-tb321fu.sh).
if tr '\0' '\n' </sys/firmware/devicetree/base/compatible 2>/dev/null | grep -qx 'lenovo,tb321fu'; then
  export KWIN_ENABLE_HW_ROTATION=0
fi
ENV

# Touch and pen report the panel's native portrait coordinates. gamescope only
# rotates touch for I2C (internal) or USB (external) devices and these are on
# SPI, so it maps them unrotated: taps land in the wrong place in Game Mode.
# Rotate them in libinput (the matrix for DT rotation 90, "right-up").
install -Dm0644 /dev/stdin "$R/usr/lib/udev/rules.d/90-steamos-arm-tb321fu-touch.rules" <<'RULES'
# Lenovo Legion Y700 Gen 3: the touch panel reports portrait coordinates, the session runs landscape.
ACTION=="add|change", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="NVTCapacitiveTouchScreen", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 1 0 -1 0 1"
ACTION=="add|change", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="NVTCapacitivePen", ENV{LIBINPUT_CALIBRATION_MATRIX}="0 1 0 -1 0 1"
RULES
# KWin already maps touch to the rotated output, so Desktop Mode replaces
# the udev calibration with identity before applying its own output rotation.
# Merge the two exact groups independently: a name in a comment or an existing
# touch group must not suppress the pen group or a missing CalibrationMatrix.
# An existing persistent /etc upper can hide the base file, so update both.
for etc in "$R/etc" "$R/var/lib/overlays/etc/upper"; do
  [[ "$etc" == "$R/etc" || -d "$etc" ]] || continue
  mkdir -p "$etc/xdg"
  cfg="$etc/xdg/kcminputrc"
  touch "$cfg"
  awk '
    BEGIN {
      group[1] = "[Libinput][0][0][NVTCapacitiveTouchScreen]"
      group[2] = "[Libinput][0][0][NVTCapacitivePen]"
      identity = "CalibrationMatrix=1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1"
    }
    /^[ \t]*\[/ {
      header = $0
      sub(/^[ \t]*/, "", header)
      sub(/[ \t]*$/, "", header)
      target = (header == group[1] || header == group[2])
      if (target) {
        seen[header] = 1
        print
        print identity
        next
      }
    }
    target && /^[ \t]*CalibrationMatrix[ \t]*=/ { next }
    { print }
    END {
      for (i = 1; i <= 2; i++) {
        if (!seen[group[i]]) {
          print ""
          print group[i]
          print identity
        }
      }
    }
  ' "$cfg" > "$W/kcminputrc"
  cat "$W/kcminputrc" > "$cfg"
done

# The Adreno 750's GMU fails to come back from runtime suspend on this tablet
# (Armada TB321FU notes): keep it powered until that is understood.
install -Dm0644 /dev/stdin "$R/usr/lib/systemd/system/steamos-arm-tb321fu-gpu-on.service" <<'UNIT'
[Unit]
Description=Lenovo Legion Y700 Gen 3: keep the GPU powered (its GMU doesn't resume)
ConditionFirmware=device-tree-compatible(lenovo,tb321fu)
Before=display-manager.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'for d in 3d00000.gpu 3d6a000.gmu; do [ -e /sys/bus/platform/devices/$d/power/control ] && echo on > /sys/bus/platform/devices/$d/power/control; done; exit 0'

[Install]
WantedBy=multi-user.target
UNIT
mkdir -p "$R/usr/lib/systemd/system/multi-user.target.wants"
ln -sfn ../steamos-arm-tb321fu-gpu-on.service "$R/usr/lib/systemd/system/multi-user.target.wants/steamos-arm-tb321fu-gpu-on.service"

# The tablet has been reported to hang during USB safe removal. Keep the
# desktop's normal unmount/error handling, but stop advertising UDisks
# PowerOff support. All filesystems still need to be unmounted before unplugging.
install -Dm0644 /dev/stdin "$R/usr/lib/udev/rules.d/90-steamos-arm-tb321fu-usb-storage.rules" <<'RULES'
# Lenovo Legion Y700 Gen 3 only: skip desktop USB power-off after unmount.
# USB SATA bridges can have ID_BUS=ata; match the USB parent instead.
# Match one complete NUL-separated compatible, not a board-name substring.
ACTION=="add|change", SUBSYSTEM=="block", SUBSYSTEMS=="usb", ENV{DEVTYPE}=="disk", PROGRAM="/usr/bin/grep -azqx lenovo,tb321fu /sys/firmware/devicetree/base/compatible", ENV{UDISKS_CAN_POWER_OFF}="0"
# The internal UFS partitions (Android's and the system's own) out of the
# desktop's Disks & Devices list, where one tap mounts them.
ACTION=="add|change", SUBSYSTEM=="block", ENV{ID_PATH}=="*ufs*", PROGRAM="/usr/bin/grep -azqx lenovo,tb321fu /sys/firmware/devicetree/base/compatible", ENV{UDISKS_IGNORE}="1"
RULES

# The cameras have no working driver on this kernel (/dev/video* fail with
# ENOMEM) and WirePlumber's v4l2 hook never completes on them, which stalls
# its event queue: no stream gets linked, no sound and no microphone. A
# profile can't be scoped to a device, so a unit gated on the tablet puts the
# override into /etc (the other devices sharing this rootfs never get it).
install -Dm0644 /dev/stdin "$R/usr/share/steamos-arm/tb321fu/52-tb321fu.conf" <<'CONF'
# Lenovo Legion Y700 Gen 3 (steamos-arm-tb321fu-setup.service): the cameras
# stall WirePlumber, and Game Mode has no xdg-desktop-portal.
wireplumber.profiles = {
  main = {
    monitor.v4l2 = disabled
    monitor.libcamera = disabled
    support.portal-permissionstore = disabled
  }
}
CONF
install -Dm0644 /dev/stdin "$R/usr/lib/systemd/system/steamos-arm-tb321fu-setup.service" <<'UNIT'
[Unit]
Description=Lenovo Legion Y700 Gen 3: audio server settings for this tablet
ConditionFirmware=device-tree-compatible(lenovo,tb321fu)
DefaultDependencies=no
After=local-fs.target
Before=sysinit.target display-manager.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/install -Dm0644 /usr/share/steamos-arm/tb321fu/52-tb321fu.conf /etc/wireplumber/wireplumber.conf.d/52-tb321fu.conf
ExecStart=/usr/bin/install -Dm0644 /usr/share/steamos-arm/tb321fu/90-lenovo-tb321fu-alsa.conf /etc/wireplumber/wireplumber.conf.d/90-lenovo-tb321fu-alsa.conf

[Install]
WantedBy=sysinit.target
UNIT
mkdir -p "$R/usr/lib/systemd/system/sysinit.target.wants"
ln -sfn ../steamos-arm-tb321fu-setup.service "$R/usr/lib/systemd/system/sysinit.target.wants/steamos-arm-tb321fu-setup.service"

# USB-C: the UCSI driver probes while the ADSP is still booting, times out
# ("PPM init failed, stop trying") and leaves no Type-C ports, roles or VBUS.
# Bind it again once the ADSP runs.
install -Dm0755 /dev/stdin "$R/usr/lib/steamos-arm/tb321fu-ucsi-rebind" <<'SH'
#!/bin/bash
set -euo pipefail
# Also guard direct invocation; remoteproc indices depend on probe order.
tr '\0' '\n' </sys/firmware/devicetree/base/compatible 2>/dev/null | grep -qx 'lenovo,tb321fu' || exit 0
[ -e /sys/class/typec/port0 ] && exit 0
ready=0
for i in $(seq 1 60); do
  for r in /sys/class/remoteproc/remoteproc*; do
    [ "$(cat "$r/firmware" 2>/dev/null)" = qcom/sm8650/lenovo/tb321fu/adsp.mdt ] || continue
    [ "$(cat "$r/state" 2>/dev/null)" = running ] || continue
    ready=1
    break
  done
  [ "$ready" = 0 ] || break
  sleep 1
done
if [ "$ready" = 0 ]; then
  echo 'TB321FU: ADSP did not reach running; leaving UCSI untouched' >&2
  exit 1
fi
sleep 8
[ -e /sys/class/typec/port0 ] && exit 0
D=/sys/bus/auxiliary/drivers/ucsi_glink.pmic_glink_ucsi
[ -w "$D/bind" ] || { echo 'TB321FU: UCSI driver is unavailable' >&2; exit 1; }
if [ -e "$D/pmic_glink.ucsi.0" ]; then
  echo pmic_glink.ucsi.0 > "$D/unbind"
  sleep 1
fi
echo pmic_glink.ucsi.0 > "$D/bind"
SH
install -Dm0644 /dev/stdin "$R/usr/lib/systemd/system/steamos-arm-tb321fu-usb.service" <<'UNIT'
[Unit]
Description=Lenovo Legion Y700 Gen 3: bind USB-C (UCSI) again once the ADSP is up
ConditionFirmware=device-tree-compatible(lenovo,tb321fu)
After=systemd-modules-load.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/lib/steamos-arm/tb321fu-ucsi-rebind
TimeoutStartSec=90

[Install]
WantedBy=multi-user.target
UNIT
ln -sfn ../steamos-arm-tb321fu-usb.service "$R/usr/lib/systemd/system/multi-user.target.wants/steamos-arm-tb321fu-usb.service"

# The tablet has one USB controller for its two USB-C ports, muxed by TLMM
# GPIO 58 (pmic-glink's c2-select): left alone the data lines stay on the
# long-side charging port, so a controller or hub on the short-side port
# (the data port) was never seen. Hold the line high to route data there.
# gpioset (libgpiod 2) keeps the line for as long as it runs.
install -Dm0755 /dev/stdin "$R/usr/lib/steamos-arm/tb321fu-usb-data-port" <<'SH'
#!/bin/bash
# Lenovo Legion Y700 Gen 3: route USB data to the short-side USB-C port.
set -euo pipefail
tr '\0' '\n' </sys/firmware/devicetree/base/compatible 2>/dev/null | grep -qx 'lenovo,tb321fu' || exit 0
chip=$(gpiodetect | awk '/\[f100000\.pinctrl\]/ { print $1; exit }')
[ -n "$chip" ] || { echo "no TLMM gpiochip" >&2; exit 1; }
# A kernel whose UCSI driver takes c2-select-gpios (the 7.2.8 tablet kernel)
# routes the port itself.
info=$(gpioinfo -c "$chip" 58) || exit 1
if grep -q 'consumer=' <<<"$info"; then
  echo "GPIO 58 is already owned; leaving its consumer in control" >&2
  exit 0
fi
exec gpioset -c "$chip" 58=1
SH
install -Dm0644 /dev/stdin "$R/usr/lib/systemd/system/steamos-arm-tb321fu-usb-data-port.service" <<'UNIT'
[Unit]
Description=Lenovo Legion Y700 Gen 3: USB data on the short-side USB-C port
ConditionFirmware=device-tree-compatible(lenovo,tb321fu)
# Let UCSI acquire c2-select before considering the userspace fallback.
Requires=steamos-arm-tb321fu-usb.service
After=steamos-arm-tb321fu-usb.service
StartLimitBurst=3
StartLimitIntervalSec=120

[Service]
ExecStart=/usr/lib/steamos-arm/tb321fu-usb-data-port
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
ln -sfn ../steamos-arm-tb321fu-usb-data-port.service "$R/usr/lib/systemd/system/multi-user.target.wants/steamos-arm-tb321fu-usb-data-port.service"

# UCSI sets the controller's role from the long-side connector: a charger or
# a PC there turns it into a device and drops whatever is on the data port.
# Put it back to host whenever something is attached to the short side.
install -Dm0755 /dev/stdin "$R/usr/lib/steamos-arm/tb321fu-usb-host" <<'SH'
#!/bin/bash
# Lenovo Legion Y700 Gen 3: host mode while the short-side port has a partner.
set -euo pipefail
tr '\0' '\n' </sys/firmware/devicetree/base/compatible 2>/dev/null | grep -qx 'lenovo,tb321fu' || exit 0
role=/sys/class/usb_role/a600000.usb-role-switch/role
[ -e /sys/class/typec/port1-partner ] || exit 0
sleep 2
# A disconnect or role-switch removal can happen during the settling delay.
[ -e /sys/class/typec/port1-partner ] && [ -e "$role" ] || exit 0
current=$(cat "$role") || exit 1
[ "$current" = host ] || echo host > "$role"
SH
install -Dm0644 /dev/stdin "$R/usr/lib/systemd/system/steamos-arm-tb321fu-usb-host.service" <<'UNIT'
[Unit]
Description=Lenovo Legion Y700 Gen 3: USB host mode for the short-side USB-C port
ConditionFirmware=device-tree-compatible(lenovo,tb321fu)
After=steamos-arm-tb321fu-usb.service
StartLimitIntervalSec=0

[Service]
Type=oneshot
ExecStart=/usr/lib/steamos-arm/tb321fu-usb-host
TimeoutStartSec=10

[Install]
WantedBy=multi-user.target
UNIT
ln -sfn ../steamos-arm-tb321fu-usb-host.service "$R/usr/lib/systemd/system/multi-user.target.wants/steamos-arm-tb321fu-usb-host.service"
install -Dm0644 /dev/stdin "$R/usr/lib/udev/rules.d/91-steamos-arm-tb321fu-usb-host.rules" <<'RULES'
# Lenovo Legion Y700 Gen 3: put host mode back when a USB-C partner or the role changes.
# SYSTEMD_WANTS only starts on device activation, not subsequent change/remove.
# Queue a nonblocking restart for each event; the service owns the delay and
# rechecks the partner. A write-induced event sees host and performs no write.
SUBSYSTEM=="typec", KERNEL=="port[01]-partner", ACTION=="add|remove", PROGRAM="/usr/bin/grep -azqx lenovo,tb321fu /sys/firmware/devicetree/base/compatible", RUN+="/usr/bin/systemctl --no-block restart steamos-arm-tb321fu-usb-host.service"
SUBSYSTEM=="usb_role", KERNEL=="a600000.usb-role-switch", ACTION=="change", PROGRAM="/usr/bin/grep -azqx lenovo,tb321fu /sys/firmware/devicetree/base/compatible", RUN+="/usr/bin/systemctl --no-block restart steamos-arm-tb321fu-usb-host.service"
RULES

# Tell the ABL each boot worked, or it gives up on the slot after 7.
O="${HERE}/../steamos-overlay"
install -Dm0755 "$O/usr/lib/steamos-arm/tablet-boot-ok" "$R/usr/lib/steamos-arm/tablet-boot-ok"
install -Dm0644 "$O/usr/lib/systemd/system/steamos-arm-tablet-boot-ok.service" "$R/usr/lib/systemd/system/steamos-arm-tablet-boot-ok.service"
ln -sfn ../steamos-arm-tablet-boot-ok.service "$R/usr/lib/systemd/system/multi-user.target.wants/steamos-arm-tablet-boot-ok.service"
log "firmware and audio profile installed"
