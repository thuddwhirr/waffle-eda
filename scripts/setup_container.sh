#!/usr/bin/env bash
# A fresh container made ready for any gate row (D147): the Python packages, Freerouting 2.4.1 with its Java and
# KiCad's libraries (scripts/fetch_tools.py), the reference boards, and the class B jar (D107) built from the
# upstream v2.4.1 source. Each step is skipped when its result is already there; about five minutes from nothing.
#
#     bash scripts/setup_container.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -c "import z3, numpy, shapely, pytest" 2>/dev/null || pip install -q z3-solver numpy shapely pytest
python3 scripts/fetch_tools.py
python3 scripts/fetch_references.py > /dev/null

if [ ! -f build/tools/freerouting-2.4.1-d107.jar ]; then
  src=build/tools/freerouting-src
  if ! git -C "$src" rev-parse -q --verify refs/tags/v2.4.1 > /dev/null 2>&1; then
    rm -rf "$src"
    git init -q "$src"
    for attempt in 1 2 3 4; do
      git -C "$src" fetch -q --depth 1 https://github.com/freerouting/freerouting.git tag v2.4.1 && break
      sleep $((2 ** attempt))
    done
  fi
  python3 scripts/patch_freerouting.py "$src" d107
fi

python3 scripts/check_env.py
