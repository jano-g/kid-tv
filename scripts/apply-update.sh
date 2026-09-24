#!/bin/bash
# Install a new kid-tv version (or go back to the previous one) and make sure
# it actually starts; otherwise put the old version back.
#
#   apply-update.sh <source-dir> <expected-version>
#
# <source-dir> is an unpacked release (or /opt/kidtv.prev for a rollback).
# The script stops and restarts kidtv.service, so it must run outside that
# service: the app starts it with `systemd-run`, scripts/update.sh runs it from
# a terminal. Cartoons, settings and the photo in /var/lib/kidtv are never
# touched.
#
# Everything is logged to /var/lib/kidtv/update.log and the outcome goes to
# /var/lib/kidtv/update-status.json, which the app shows after it restarts.
#
# Environment (defaults are for the Raspberry Pi; tests override them):
#   KIDTV_DEST            installed app            (/opt/kidtv)
#   KIDTV_DATA_DIR        data directory           (/var/lib/kidtv)
#   KIDTV_SYSTEMCTL       systemctl command        (systemctl)
#   KIDTV_HEALTH_URL      status endpoint          (http://127.0.0.1/api/status)
#   KIDTV_HEALTH_TIMEOUT  seconds to wait for it   (120)
#   KIDTV_HEALTH_INTERVAL seconds between tries    (3)
#   KIDTV_SETUP_CMD       replaces "bash <src>/image/setup.sh" (tests)
set -uo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <source-dir> <expected-version>" >&2
  exit 2
fi
SRC_IN="$1"
WANT="${2#v}"
DEST="${KIDTV_DEST:-/opt/kidtv}"
PREV="${DEST}.prev"
DATA="${KIDTV_DATA_DIR:-/var/lib/kidtv}"
SYSTEMCTL="${KIDTV_SYSTEMCTL:-systemctl}"
HEALTH_URL="${KIDTV_HEALTH_URL:-http://127.0.0.1/api/status}"
HEALTH_TIMEOUT="${KIDTV_HEALTH_TIMEOUT:-120}"
HEALTH_INTERVAL="${KIDTV_HEALTH_INTERVAL:-3}"
LOG="$DATA/update.log"
STATUS="$DATA/update-status.json"

mkdir -p "$DATA/updates"
# Keep the log small: the last ~2000 lines are plenty.
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 4000 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
if [ -t 1 ]; then
  exec > >(tee -a "$LOG") 2>&1
else
  exec >>"$LOG" 2>&1
fi

version_of() {
  python3 - "$1" <<'PY' 2>/dev/null
import re, sys
try:
    text = open(sys.argv[1] + "/kidtv/__init__.py", encoding="utf-8").read()
except OSError:
    sys.exit(0)
m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
print(m.group(1) if m else "")
PY
}

FROM="$(version_of "$DEST")"

status() {  # state message
  python3 - "$STATUS" "$1" "$FROM" "$WANT" "${2:-}" <<'PY'
import datetime, json, os, sys
path, state, frm, to, msg = sys.argv[1:6]
data = {"state": state, "from": frm, "to": to, "message": msg,
        "time": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "shown": False}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
    fh.flush()
    os.fsync(fh.fileno())
os.replace(tmp, path)
PY
}

run_setup() {  # source-dir
  if [ -n "${KIDTV_SETUP_CMD:-}" ]; then
    KIDTV_SRC="$1" KIDTV_DEST="$DEST" bash -c "$KIDTV_SETUP_CMD"
  else
    KIDTV_SRC="$1" KIDTV_DEST="$DEST" bash "$1/image/setup.sh"
  fi
}

healthy() {  # expected-version
  local deadline v
  deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
  while [ "$(date +%s)" -le "$deadline" ]; do
    v="$(python3 - "$HEALTH_URL" <<'PY' 2>/dev/null
import json, sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=3) as r:
    print(json.load(r).get("version", ""))
PY
)"
    if [ "$v" = "$1" ]; then
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

restart_app() {
  $SYSTEMCTL daemon-reload || true
  $SYSTEMCTL restart kidtv.service
}

echo
echo "=== $(date -Iseconds) kid-tv update ${FROM:-?} -> $WANT (source: $SRC_IN)"

if [ ! -f "$SRC_IN/kidtv/__init__.py" ] || [ ! -f "$SRC_IN/image/setup.sh" ]; then
  echo "source directory does not look like kid-tv"
  status failed "bad-source"
  exit 1
fi

# A rollback installs /opt/kidtv.prev, but the backup step below overwrites
# that directory – work from a copy.
SRC="$SRC_IN"
if [ -d "$PREV" ] && [ "$(realpath "$SRC_IN")" = "$(realpath "$PREV")" ]; then
  SRC="$DATA/updates/rollback-src"
  rm -rf "$SRC"
  cp -a "$PREV" "$SRC"
fi

status running ""

# Stop the TV (it saves the current position on SIGTERM) and show the
# "updating" picture the app prepared, so the screen is not just black.
$SYSTEMCTL stop kidtv.service || true
if command -v fbi >/dev/null 2>&1 && [ -f "$DATA/updating.png" ] && [ -e /dev/fb0 ]; then
  fbi -T 1 -d /dev/fb0 --noverbose -a "$DATA/updating.png" </dev/null >/dev/null 2>&1 &
fi

# Backup of the running version, for the automatic and the manual rollback.
if [ -d "$DEST" ]; then
  rm -rf "$PREV"
  cp -a "$DEST" "$PREV"
fi

if run_setup "$SRC"; then
  echo "setup finished, starting the new version"
  if restart_app && healthy "$WANT"; then
    echo "=== kid-tv $WANT is running"
    status success ""
    rm -rf "$DATA/updates/rollback-src"
    exit 0
  fi
  echo "kid-tv $WANT did not start within ${HEALTH_TIMEOUT}s"
else
  echo "setup of $WANT failed"
fi

# --- automatic rollback -------------------------------------------------------
if [ -z "$FROM" ] || [ ! -d "$PREV" ]; then
  echo "no previous version to go back to"
  restart_app || true
  status failed "no-previous-version"
  exit 1
fi
echo "=== going back to $FROM"
if KIDTV_SKIP_APT=1 run_setup "$PREV" && restart_app && healthy "$FROM"; then
  echo "=== back on $FROM"
  status rolled_back "new-version-did-not-start"
  exit 1
fi
echo "rollback to $FROM failed as well"
status failed "rollback-failed"
exit 1
