#!/usr/bin/env bash
set -euo pipefail

# Convert the markdown slides to a PowerPoint using pandoc.
# Requires: pandoc with PowerPoint writer.
# Install on Debian/Ubuntu: sudo apt-get install pandoc
# Alternatively, use a Python script with python-pptx for custom styling.

MD_FILE="vac_bot_slides.md"
OUT_FILE="vac_bot_deck.pptx"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "pandoc not found. Install pandoc or convert using another tool." >&2
  exit 1
fi

pandoc -t pptx --slide-level=2 -o "$OUT_FILE" "$MD_FILE"
echo "Created $OUT_FILE"
