"""A gate row replayed from a frozen router session (D147).

The router is the slow part of a gate row (4 to 70 minutes) and its only unrepeatable one (buspirate5 ended at 8,
10 and 9 unrouted on one DSN, D145). Everything else in the row, the export before it and the finishing after it,
is our code and deterministic. A row's router output is frozen once, as its session file, beside the md5 of the
DSN it was routed from; a replay runs the whole row with the jar replaced by that session. It takes minutes, gives
the same board every time, and whatever changes in it is our code's doing. When the export changes, the DSN no
longer matches, the replay stops with `StaleSession`, and the row has to be routed and frozen again.

    tests/fixtures/sessions/<key>/board.ses.gz   the router's session, gzip without a timestamp
    tests/fixtures/sessions/<key>/router.log     its log lines the row reads (passes, unrouted, violations)
    tests/fixtures/sessions/<key>/manifest.json  the DSN's md5, the router's settings and jar (`router_record`),
                                                 the commit, the gate and the row it produced
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from waffle_eda.bench import references as refs
from waffle_eda.route import freerouting as fr


class StaleSession(RuntimeError):
    """The DSN the export writes now is not the one the frozen session was routed from."""


def fixtures_dir() -> Path:
    return refs.repo_root() / "tests" / "fixtures" / "sessions"


def frozen_keys() -> list[str]:
    root = fixtures_dir()
    return sorted(p.parent.name for p in root.glob("*/manifest.json")) if root.is_dir() else []


def manifest(key: str) -> dict:
    return json.loads((fixtures_dir() / key / "manifest.json").read_text())


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def commit() -> str:
    run = subprocess.run(["git", "-C", str(refs.repo_root()), "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True)
    return run.stdout.strip() or "unknown"


def router_lines(text: str) -> str:
    """The lines of a router log that `freerouting.parse_log` reads."""
    return "".join(line + "\n" for line in text.splitlines() if fr._PASS.search(line) or fr._STAGE.search(line))


def freeze(key: str, work_dir: Path, row: dict) -> Path:
    """Freeze the router output of the row last run in ``work_dir`` (`build/fr/<key>`) with the row it gave."""
    ses, dsn, log = work_dir / "board.ses", work_dir / "board.dsn", work_dir / "run.log"
    if not ses.is_file() or ses.stat().st_size == 0:
        raise FileNotFoundError(f"{key}: no session in {work_dir}")
    if not (work_dir / "router.json").is_file():
        raise FileNotFoundError(f"{key}: no router.json in {work_dir}: the run predates the record")
    out = fixtures_dir() / key
    out.mkdir(parents=True, exist_ok=True)
    (out / "board.ses.gz").write_bytes(gzip.compress(ses.read_bytes(), mtime=0))
    (out / "router.log").write_text(router_lines(log.read_text()))
    facts = {"key": key, "dsn_md5": md5(dsn), "session_md5": md5(ses), "frozen_at": commit(), "row": row,
             "router": json.loads((work_dir / "router.json").read_text())}
    (out / "manifest.json").write_text(json.dumps(facts, indent=1, sort_keys=True) + "\n")
    return out


@contextlib.contextmanager
def replaying(key: str):
    """Within this block the router's run is the frozen session of ``key``: `freerouting.run_jar` is replaced by
    a check that the DSN is the one the session was routed from, and a copy of the session and its log."""
    folder = fixtures_dir() / key
    if not (folder / "manifest.json").is_file():
        raise FileNotFoundError(f"{key}: no frozen session in {folder}")
    facts = manifest(key)
    real = fr.run_jar

    def run_jar(dsn: Path, ses: Path, log: Path, passes: int, threads: int, _timeout_s: float,
                edge_clearance_mm: float | None = None, fanout: bool = fr.FANOUT, gui: bool = fr.GUI,
                jar: Path | None = None, via_costs: int | None = None, plane_via_costs: int | None = None,
                ripup_costs: int | None = None):
        got = md5(dsn)
        if got != facts["dsn_md5"]:
            raise StaleSession(f"{key}: the export wrote DSN {got[:10]}, the frozen session was routed from "
                               f"{facts['dsn_md5'][:10]} (frozen at {facts['frozen_at']}): route the row again and "
                               f"freeze it (scripts/freeze_sessions.py)")
        with tempfile.TemporaryDirectory() as tmp:  # the settings this run would hand the jar, and the jar
            settings = fr.settings_json(Path(tmp), threads, passes, fanout=fanout, edge_clearance_mm=edge_clearance_mm,
                                        gui=gui, via_costs=via_costs, plane_via_costs=plane_via_costs,
                                        ripup_costs=ripup_costs)
            record = fr.router_record(settings, jar or fr.jar_path())
        if record != facts["router"]:
            differs = sorted(k for k in record if record[k] != facts["router"].get(k))
            raise StaleSession(f"{key}: the router would run with other settings or another jar ({differs}) than "
                               f"the frozen session's (frozen at {facts['frozen_at']}): route the row again and "
                               f"freeze it")
        ses.write_bytes(gzip.decompress((folder / "board.ses.gz").read_bytes()))
        log.write_text((folder / "router.log").read_text())
        return 0, False

    fr.run_jar = run_jar
    try:
        yield facts
    finally:
        fr.run_jar = real
