#!/bin/bash
# Update kid-tv to the newest release from a terminal (SSH or a keyboard):
#
#   curl -fsSL https://raw.githubusercontent.com/jano-g/kid-tv/main/scripts/update.sh | sudo bash
#   curl -fsSL .../scripts/update.sh | sudo bash -s v0.2.0      # a specific version
#
# Normally you do not need this: from version 0.2.0 the TV updates itself from
# the web page (Systém → Aktualizácia) or the on-screen menu. This script is
# the one-time way up from 0.1.0 and a fallback if the web page ever breaks.
# Cartoons, settings and the photo are kept.

main() {
  set -euo pipefail
  local repo="${KIDTV_REPO:-jano-g/kid-tv}"
  local data="${KIDTV_DATA_DIR:-/var/lib/kidtv}"
  local want="${1:-latest}"
  local work="$data/updates"

  if [ "$(id -u)" -ne 0 ]; then
    echo "Spusti ako root, napríklad: curl -fsSL …/update.sh | sudo bash" >&2
    exit 1
  fi
  mkdir -p "$work"

  local base="${KIDTV_API:-https://api.github.com}"
  local api="$base/repos/$repo/releases/latest"
  [ "$want" = "latest" ] || api="$base/repos/$repo/releases/tags/v${want#v}"
  echo "Hľadám verziu ($repo, $want)…"
  local json
  if ! json="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api")"; then
    echo "Nepodarilo sa spojiť s GitHubom. Je telka na internete a repozitár $repo verejný?" >&2
    exit 1
  fi

  local version bundle_url sha_url
  read -r version bundle_url sha_url < <(python3 -c '
import json, re, sys
d = json.load(sys.stdin)
assets = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
for name, url in assets.items():
    m = re.match(r"^kid-tv-app-v?(\d+\.\d+\.\d+)\.tar\.gz$", name)
    if m and name + ".sha256" in assets:
        print(m.group(1), url, assets[name + ".sha256"])
        break
' <<<"$json") || true
  if [ -z "${version:-}" ]; then
    echo "Vydanie nemá aktualizačný balík (kid-tv-app-*.tar.gz)." >&2
    exit 1
  fi

  local installed
  installed="$(python3 -c 'import re,sys; print(re.search(r"__version__\s*=\s*\"([^\"]+)\"", open(sys.argv[1]).read()).group(1))' "${KIDTV_DEST:-/opt/kidtv}/kidtv/__init__.py" 2>/dev/null || echo "?")"
  echo "Nainštalovaná verzia: $installed, inštalujem: $version"

  local bundle="$work/kid-tv-app-v$version.tar.gz"
  curl -fL --progress-bar -o "$bundle" "$bundle_url"
  local expected actual
  expected="$(curl -fsSL "$sha_url" | awk '{print $1}')"
  actual="$(sha256sum "$bundle" | awk '{print $1}')"
  if [ "$expected" != "$actual" ]; then
    echo "Kontrolný súčet nesedí, balík je poškodený. Skús to znova." >&2
    rm -f "$bundle"
    exit 1
  fi

  local target="$work/kid-tv-v$version"
  rm -rf "$target"
  mkdir -p "$target"
  python3 - "$bundle" "$target" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as tar:
    if hasattr(tarfile, "data_filter"):
        tar.extractall(sys.argv[2], filter="data")
    else:
        tar.extractall(sys.argv[2])
PY
  local app="$target/kid-tv"
  [ -f "$app/scripts/apply-update.sh" ] || app="$target"

  # Let the new version draw the "updating" picture for the screen.
  PYTHONPATH="$app" KIDTV_DATA_DIR="$data" python3 -m kidtv render-updating >/dev/null 2>&1 || true

  echo "Inštalujem… (telka sa na chvíľu vypne)"
  local rc=0
  KIDTV_DATA_DIR="$data" bash "$app/scripts/apply-update.sh" "$app" "$version" </dev/null || rc=$?

  echo
  python3 - "$data/update-status.json" <<'PY' || true
import json, sys
s = json.load(open(sys.argv[1]))
msg = {"success": "Hotovo, telka beží na verzii {to}.",
       "rolled_back": "Verzia {to} nenaštartovala, telka sa vrátila na {from}.",
       "failed": "Aktualizácia zlyhala ({message}). Pozri /var/lib/kidtv/update.log."}
print(msg.get(s.get("state"), "Stav: {state}").format(**{k: v or "" for k, v in s.items()}))
PY
  # Back to the TV picture when this ran on the Pi's own keyboard.
  if [ -z "${SSH_CONNECTION:-}" ] && command -v chvt >/dev/null 2>&1; then
    chvt 1 || true
  fi
  return "$rc"
}

# Wrapped in a function so that `curl … | bash` reads the whole script first.
main "$@"
