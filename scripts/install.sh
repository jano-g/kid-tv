#!/bin/bash
# Install kid-tv on an existing Raspberry Pi OS Lite (64-bit, Bookworm).
#
#   git clone https://github.com/jano-g/kid-tv.git
#   sudo bash kid-tv/scripts/install.sh
#
# Afterwards reboot – the TV starts automatically.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi
SRC="$(cd "$(dirname "$0")/.." && pwd)"
KIDTV_SRC="$SRC" bash "$SRC/image/setup.sh"
hostnamectl set-hostname kid 2>/dev/null || true
sed -i 's/127\.0\.1\.1.*/127.0.1.1\tkid/' /etc/hosts 2>/dev/null || true
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_wifi_country SK || true
fi
echo
echo "kid-tv installed. Reboot now:  sudo reboot"
