#!/usr/bin/env python3
"""Fetch the pinned Freerouting jar (GPL-3.0, https://github.com/freerouting/freerouting) into build/tools/.

    python3 scripts/fetch_freerouting.py

The jar is never committed (64 MB). Its version and checksum are pinned in `waffle_eda/route/freerouting.py`;
`WAFFLE_FREEROUTING_JAR` points the tool at a jar the owner supplies instead.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import urllib.request

import _path  # noqa: F401
from waffle_eda.route import freerouting as fr


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    jar = fr.jar_path()
    if jar.is_file() and sha256(jar) == fr.JAR_SHA256:
        print(f"{jar} present, checksum ok")
        return 0
    jar.parent.mkdir(parents=True, exist_ok=True)
    tmp = jar.with_suffix(".part")
    print(f"fetching {fr.JAR_URL}")
    if shutil.which("curl"):  # follows the release redirect and honours the environment's proxy settings
        subprocess.run(["curl", "-sSL", "--fail", "-o", str(tmp), fr.JAR_URL], check=True)
    else:
        with urllib.request.urlopen(fr.JAR_URL, timeout=120) as r, open(tmp, "wb") as out:
            shutil.copyfileobj(r, out)
    got = sha256(tmp)
    if got != fr.JAR_SHA256:
        tmp.unlink()
        print(f"checksum mismatch: {got} != {fr.JAR_SHA256}", file=sys.stderr)
        return 1
    tmp.rename(jar)
    print(f"{jar} fetched, checksum ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
