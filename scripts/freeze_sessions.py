#!/usr/bin/env python3
"""Freeze the router output of the gate rows last run into `tests/fixtures/sessions/<key>/` (D147): the session,
the router's log lines, the DSN's md5 and the row (`build/fr/<key>/row.json`). A replay (`WAFFLE_REPLAY=1
scripts/gate.py ...`, `scripts/replay.py`, `pytest -m replay`) then runs the row from it in minutes.

    python3 scripts/freeze_sessions.py [<key> ...]            # every row with a session under build/fr when none named
    python3 scripts/freeze_sessions.py --rebase [<key> ...]   # after a replay: the frozen row becomes the replayed
                                                              # one, the session kept (a finishing change made on
                                                              # purpose; the next replay compares with it)

A row routed under an overridden configuration or router budget, or itself a replay, is not frozen: the frozen
session stands for the class's own configuration.
"""
import json
import sys

import _path  # noqa: F401
from waffle_eda.bench import references as refs, replay


def rebase(keys: list[str]) -> int:
    status = 0
    for key in keys or replay.frozen_keys():
        row_file = refs.repo_root() / "build" / "fr" / key / "row.json"
        row = json.loads(row_file.read_text()) if row_file.is_file() else {}
        if not row.get("replayed"):
            print(f"{key}: the last row is not a replay; replay it first (scripts/replay.py)")
            status = 1
            continue
        facts = replay.manifest(key)
        facts["row"] = {**row, "replayed": False, "rebased_at": replay.commit()}
        (replay.fixtures_dir() / key / "manifest.json").write_text(json.dumps(facts, indent=1, sort_keys=True) + "\n")
        print(f"{key}: frozen row rebased (final {row['final']}, {'pass' if row['pass'] else 'FAIL'})")
    return status


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--rebase":
        return rebase(argv[1:])
    root = refs.repo_root() / "build" / "fr"
    keys = argv or sorted(p.parent.name for p in root.glob("*/row.json"))
    status = 0
    for key in keys:
        work = root / key
        row_file = work / "row.json"
        if not row_file.is_file():
            print(f"{key}: no row.json in {work}: run its gate row first")
            status = 1
            continue
        row = json.loads(row_file.read_text())
        why = ("a replay" if row.get("replayed") else "an overridden configuration" if row.get("overridden")
               else "an overridden budget" if set(row.get("budget", {})) - {"timeout_s"} else None)
        if why:
            print(f"{key}: not frozen, the row ran under {why}")
            status = 1
            continue
        try:
            out = replay.freeze(key, work, row)
        except FileNotFoundError as e:
            print(e)
            status = 1
            continue
        print(f"{key}: frozen in {out.relative_to(refs.repo_root())} (dsn {row['dsn']}, "
              f"{'pass' if row['pass'] else 'FAIL'})")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
