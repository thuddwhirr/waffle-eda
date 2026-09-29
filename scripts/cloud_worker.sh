#!/usr/bin/env bash
# One gate row in a cloud worker session (D147): the container set up, the row routed, its results written to
# results/<tag>/<key>/ and pushed to <branch>, which the orchestrating session reads back. The row's session is
# frozen there too (board.ses.gz, router.log, manifest.json), so the orchestrator can adopt it as the fixture.
#
#     bash scripts/cloud_worker.sh <gate a|b> <key> <tag> <branch>
set -euo pipefail
cd "$(dirname "$0")/.."
gate=$1 key=$2 tag=$3 branch=$4
out=results/$tag/$key
mkdir -p "$out"

bash scripts/setup_container.sh > "$out/setup.log" 2>&1 || { tail -20 "$out/setup.log"; echo "setup failed" > "$out/FAILED"; }

if [ ! -f "$out/FAILED" ]; then
  start=$(date +%s)
  python3 scripts/gate.py "$gate" "$key" > "$out/gate.full.log" 2>&1 || true
  grep -v "Debug:" "$out/gate.full.log" | grep -E "^=== GATE|^  (pass|FAIL) " > "$out/gate.log" || true
  echo "$(( $(date +%s) - start )) s" > "$out/seconds"
  cp "build/fr/$key/row.json" "$out/" 2>/dev/null || true
  cp "build/bench/$key-residue.md" "$out/residue.md" 2>/dev/null || true
  python3 - "$key" "$out" <<'EOF' || true
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, ".")
from waffle_eda.bench import replay
key, out = sys.argv[1], Path(sys.argv[2])
work = Path("build/fr") / key
row = json.loads((work / "row.json").read_text())
frozen = replay.freeze(key, work, row)
for name in ("board.ses.gz", "router.log", "manifest.json"):
    shutil.copy(frozen / name, out / name)
shutil.rmtree(frozen)  # the fixture is the orchestrator's to adopt, not the worker's
EOF
  git checkout -- tests/fixtures/sessions 2>/dev/null || true
  rm -f "$out/gate.full.log"
fi

git add "$out"
git commit -q -m "Gate row $key ($tag)" -m "Worker session of D147: scripts/cloud_worker.sh $gate $key $tag" -- "$out"
for attempt in 1 2 3 4; do
  git push -q origin "HEAD:refs/heads/$branch" && break
  sleep $((2 ** attempt))
done
cat "$out/gate.log" 2>/dev/null || cat "$out/FAILED"
