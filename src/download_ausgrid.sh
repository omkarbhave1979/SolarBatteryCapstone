#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p data/raw
target=data/raw/ausgrid.zip
if [ -e "$target" ]; then
    printf '%s\n' "$target already exists"
    exit 0
fi
tmp=$(mktemp data/raw/ausgrid.XXXXXX)
trap 'rm -f "$tmp"' EXIT
curl --fail --location --retry 2 --max-time 300 \
    https://pierreh.eu/downloads/Ausgrid_solar_home_data.zip --output "$tmp"
python3 -m zipfile -t "$tmp"
mv "$tmp" "$target"
