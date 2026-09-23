#!/bin/bash
# Session start for Claude Code on the web: everything a session needs that a fresh container lacks, so the
# plan's "confirm the state first" is one command, not a setup round. Idempotent; the container state is
# cached once this completes.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Python packages (pyproject.toml): z3, numpy, shapely, pytest. KiCad's pcbnew comes with the image.
python3 -m pip install -q z3-solver numpy shapely pytest 2>&1 | grep -v "Running pip as the 'root' user" || true

# Freerouting 2.4.1 is compiled for Java 25; the image ships 21 (waffle_eda/route/freerouting.py).
if ! /usr/lib/jvm/java-25-openjdk-amd64/bin/java -version >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -q openjdk-25-jdk-headless >/dev/null 2>&1 || apt-get update -q >/dev/null 2>&1 && apt-get install -y -q openjdk-25-jdk-headless >/dev/null 2>&1
fi

# KiCad's symbol and footprint libraries: stages 2 to 5 of a design read them (the image ships pcbnew without them).
if [ ! -d /usr/share/kicad/footprints ] || [ -z "$(ls -A /usr/share/kicad/footprints 2>/dev/null)" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -q kicad-symbols kicad-footprints >/dev/null 2>&1 || (apt-get update -q >/dev/null 2>&1 && apt-get install -y -q kicad-symbols kicad-footprints >/dev/null 2>&1)
fi

# The pinned Freerouting jar (build/tools/, never committed) and the reference boards (references/).
python3 scripts/fetch_freerouting.py
python3 scripts/fetch_references.py

python3 scripts/check_env.py
