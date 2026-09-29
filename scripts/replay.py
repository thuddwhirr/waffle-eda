#!/usr/bin/env python3
"""Replay gate rows from their frozen router sessions, several at once, and compare each with the row it was frozen
from (D147). No router runs, so rows may run in parallel; a class B row takes 1 to 6 minutes.

    python3 scripts/replay.py [<key> ...] [-j N]      # every frozen row when none named; N rows at a time (3)

Per row: PASS or FAIL under the class's criterion, and whether the board came out the same as the frozen row's
(`imported` and `final` digests). A different imported board means the import changed; a different final board
means the finishing did. A stale session (the export changed the DSN) is a FAIL that names itself. Logs go to
build/replay/<key>.log. Exit 0 when every row passes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import _path  # noqa: F401
from waffle_eda.bench import references as refs, replay


def run(key: str) -> tuple[str, float]:
    facts = replay.manifest(key)
    gate = facts["row"]["gate"]
    log = refs.repo_root() / "build" / "replay" / f"{key}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    row_file = refs.repo_root() / "build" / "fr" / key / "row.json"
    if row_file.is_file():
        row_file.unlink()
    t0 = time.time()
    with log.open("w") as out:
        subprocess.run([sys.executable, str(refs.repo_root() / "scripts" / "gate.py"), gate, key], stdout=out,
                       stderr=subprocess.STDOUT, env={**os.environ, "WAFFLE_REPLAY": "1"})
    return key, time.time() - t0


def main(argv: list[str]) -> int:
    jobs = 3
    if "-j" in argv:
        i = argv.index("-j")
        jobs = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    keys = argv or replay.frozen_keys()
    missing = [k for k in keys if k not in replay.frozen_keys()]
    if missing:
        print(f"no frozen session: {missing}")
        return 2
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        times = dict(pool.map(run, keys))
    failed = 0
    for key in keys:
        frozen = replay.manifest(key)["row"]
        row_file = refs.repo_root() / "build" / "fr" / key / "row.json"
        if not row_file.is_file():
            tail = (refs.repo_root() / "build" / "replay" / f"{key}.log").read_text().strip().splitlines()[-1:]
            print(f"FAIL  {key:<24} no row: {tail[0][:200] if tail else 'no output'}")
            failed += 1
            continue
        row = json.loads(row_file.read_text())
        same = ("same board" if (row["imported"], row["final"]) == (frozen["imported"], frozen["final"])
                else "import differs" if row["imported"] != frozen["imported"] else "finishing differs")
        failed += not row["pass"]
        head = row["detail"].split(" | ")
        connected = next((h.split(",")[0] for h in head if h.startswith("connected")), "")
        print(f"{'pass' if row['pass'] else 'FAIL'}  {key:<24} {connected:<20} "
              f"{same} (frozen {'pass' if frozen['pass'] else 'FAIL'}), {times[key]:.0f} s")
        residue = next((h for h in head if h.startswith("residue")), "")
        if residue:
            print(f"      {residue}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
