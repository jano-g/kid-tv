#!/bin/bash
# Build the app bundle an update installs: kid-tv-app-vX.Y.Z.tar.gz + .sha256.
#
#   scripts/build_bundle.sh v0.2.0 dist/
#
# Takes the files git tracks (without tests), stamps the version into
# kidtv/__init__.py and packs them under a kid-tv/ directory. Used by the
# Release workflow; handy locally to test an update by hand.
set -euo pipefail

version="${1:?usage: build_bundle.sh vX.Y.Z [out-dir]}"
out="${2:-dist}"
if ! [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "version must look like v1.2.3, got '$version'" >&2
  exit 1
fi
root="$(cd "$(dirname "$0")/.." && pwd)"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/kid-tv" "$out"

(cd "$root" && git ls-files -z | grep -zv '^tests/' | tar --null -T - -cf -) | tar -xf - -C "$stage/kid-tv"
sed -i "s/^__version__ = .*/__version__ = \"${version#v}\"/" "$stage/kid-tv/kidtv/__init__.py"
grep -q "__version__ = \"${version#v}\"" "$stage/kid-tv/kidtv/__init__.py"

name="kid-tv-app-$version.tar.gz"
tar -C "$stage" --sort=name --owner=0 --group=0 --numeric-owner -czf "$out/$name" kid-tv
(cd "$out" && sha256sum "$name" > "$name.sha256")
echo "$out/$name"
