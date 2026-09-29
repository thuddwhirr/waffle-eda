#!/usr/bin/env python3
"""Read back the gate rows cloud workers pushed (D147, `scripts/cloud_worker.sh`): every branch
`claude/gate-<tag>*`, fetched, one line a row with its verdict, connected nets, the router's unrouted count, the
residue, the digests and the time.

    python3 scripts/collect_workers.py <tag prefix>          # e.g. nb1 for claude/gate-nb1-r1-..., -r2-...
    python3 scripts/collect_workers.py <tag prefix> --adopt  # also copy each worker's frozen session into
                                                             # tests/fixtures/sessions/<key>/ (the last one wins)
"""
import json
import re
import subprocess
import sys

import _path  # noqa: F401
from waffle_eda.bench import references as refs


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(refs.repo_root()), *args], capture_output=True, text=True).stdout


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    prefix, adopt = argv[0], "--adopt" in argv
    branches = sorted(line.split("refs/heads/")[1] for line in git("ls-remote", "origin",
                                                                  f"refs/heads/claude/gate-{prefix}*").splitlines())
    if not branches:
        print(f"no branch claude/gate-{prefix}* on origin yet")
        return 1
    for branch in branches:
        git("fetch", "-q", "origin", branch)
        files = git("ls-tree", "-r", "--name-only", "FETCH_HEAD", "results/").splitlines()
        rows = sorted({f.split("/")[1] + "/" + f.split("/")[2] for f in files if f.count("/") >= 3})
        for tagkey in rows:
            tag, key = tagkey.split("/")
            base = f"results/{tag}/{key}"
            if f"{base}/row.json" not in files:
                print(f"{tag:<10} {key:<24} no row: {git('show', f'FETCH_HEAD:{base}/FAILED').strip() or 'see setup.log'}")
                continue
            row = json.loads(git("show", f"FETCH_HEAD:{base}/row.json"))
            detail = row["detail"]
            connected = re.search(r"connected (\d+/\d+)", detail)
            unrouted = re.search(r"router reports (\d+) unrouted", detail)
            residue = re.search(r"residue ([^|]*?)(?: \(|\|)", detail)
            seconds = git("show", f"FETCH_HEAD:{base}/seconds").strip()
            print(f"{tag:<10} {key:<24} {'pass' if row['pass'] else 'FAIL'}  connected "
                  f"{connected.group(1) if connected else '?':<8} router {unrouted.group(1) if unrouted else '?':>3} "
                  f"unrouted  dsn {row['dsn']} imported {row['imported']} final {row['final']}  {seconds}  "
                  f"residue {residue.group(1).strip() if residue else '-'}")
            if adopt and f"{base}/manifest.json" in files:
                out = refs.repo_root() / "tests" / "fixtures" / "sessions" / key
                out.mkdir(parents=True, exist_ok=True)
                for name in ("manifest.json", "router.log"):
                    (out / name).write_text(git("show", f"FETCH_HEAD:{base}/{name}"))
                blob = subprocess.run(["git", "-C", str(refs.repo_root()), "show", f"FETCH_HEAD:{base}/board.ses.gz"],
                                      capture_output=True).stdout
                (out / "board.ses.gz").write_bytes(blob)
                print(f"           adopted as tests/fixtures/sessions/{key}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
