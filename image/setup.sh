#!/bin/bash
# Provision kid-tv on Raspberry Pi OS Lite (Bookworm, 64-bit).
#
# Used both by the pi-gen image build (inside the chroot) and by
# scripts/install.sh on an already running Raspberry Pi. Idempotent.
#
# Environment:
#   KIDTV_SRC   directory with the repository checkout (default: dir of this script/..)
#   KIDTV_SKIP_APT=1  skip apt-get (packages already installed by pi-gen)
set -euo pipefail

SRC="${KIDTV_SRC:-$(cd "$(dirname "$0")/.." && pwd)}"
DEST=/opt/kidtv
BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot

echo "kid-tv setup from $SRC"

# --- packages ---------------------------------------------------------------
if [ "${KIDTV_SKIP_APT:-0}" != "1" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  xargs -a "$SRC/image/stage-kidtv/00-install/00-packages" apt-get install -y --no-install-recommends
fi

# --- application ------------------------------------------------------------
mkdir -p "$DEST"
rsync -a --delete --exclude '.git' --exclude 'tests' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$SRC/" "$DEST/"
chmod +x "$DEST/image/kidtv-splash.sh" "$DEST/scripts/"*.sh 2>/dev/null || true
mkdir -p /var/lib/kidtv/media/kanal1 /var/lib/kidtv/media/kanal2 /var/lib/kidtv/media/kanal3 /etc/kidtv
[ -f /etc/kidtv/mpv.conf ] || install -m 644 "$SRC/image/mpv.conf" /etc/kidtv/mpv.conf
install -m 644 "$SRC/image/asound.conf" /etc/asound.conf

# --- services ---------------------------------------------------------------
install -m 644 "$SRC/systemd/kidtv.service" /etc/systemd/system/kidtv.service
install -m 644 "$SRC/systemd/kidtv-splash.service" /etc/systemd/system/kidtv-splash.service
systemctl enable kidtv.service kidtv-splash.service
# No login prompt on the TV screen, no swap file wearing out the SD card.
systemctl disable getty@tty1.service 2>/dev/null || true
systemctl disable dphys-swapfile.service 2>/dev/null || true
systemctl enable avahi-daemon.service NetworkManager.service 2>/dev/null || true
# Journal in RAM only – fewer SD-card writes, survives power cuts better.
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/kidtv.conf <<'JEOF'
[Journal]
Storage=volatile
RuntimeMaxUse=32M
JEOF

# --- NetworkManager hotspot DNS ------------------------------------------------
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
install -m 644 "$SRC/image/nm-dnsmasq-kidtv.conf" /etc/NetworkManager/dnsmasq-shared.d/kidtv.conf
# Wi-Fi power saving causes dropouts on the Pi; turn it off.
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/kidtv-wifi-powersave.conf <<'NEOF'
[connection]
wifi.powersave = 2
NEOF

# --- boot configuration --------------------------------------------------------
CFG="$BOOT/config.txt"
if [ -f "$CFG" ] && ! grep -q '^# kid-tv' "$CFG"; then
  cat >> "$CFG" <<'CEOF'

# kid-tv
disable_splash=1
hdmi_force_hotplug=1
# Sound only over HDMI (no headphone jack), so ALSA's default card is the HDMI port.
dtparam=audio=off
CEOF
fi
CMD="$BOOT/cmdline.txt"
if [ -f "$CMD" ]; then
  line="$(head -n1 "$CMD")"
  for opt in quiet loglevel=0 logo.nologo vt.global_cursor_default=0 consoleblank=0 "video=HDMI-A-1:1920x1080M@60D"; do
    case " $line " in *" $opt "*) ;; *) line="$line $opt";; esac
  done
  # Keep the boot text off the TV: kernel messages to tty3 instead of tty1.
  line="$(echo "$line" | sed 's/console=tty1/console=tty3/')"
  echo "$line" > "$CMD"
fi

# --- misc ------------------------------------------------------------------------
if command -v timedatectl >/dev/null 2>&1 && [ -z "${KIDTV_IN_CHROOT:-}" ]; then
  timedatectl set-timezone Europe/Bratislava || true
else
  ln -sf /usr/share/zoneinfo/Europe/Bratislava /etc/localtime
  echo "Europe/Bratislava" > /etc/timezone
fi
echo "kid-tv setup done"
