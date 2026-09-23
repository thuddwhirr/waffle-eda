#!/usr/bin/env python3
"""Fetch the tools stage 5 needs that are not in the container image: Freerouting and the Java it runs on.

    python3 scripts/fetch_tools.py           # both, into build/tools/ (skipped when already there)
    python3 scripts/fetch_tools.py --check   # only say what is there

Freerouting 2.4.1 is compiled for Java 25 and the container has Java 21 (D56), so a Temurin JDK 25 goes next to
the jar. Both come from GitHub releases, which the egress policy allows; Maven Central and Adoptium's API do not
answer from here (measured 2026-09-23). `waffle_eda.route.freerouting` finds both under `build/tools/` and
`scripts/check_env.py` reports them. `WAFFLE_FREEROUTING_JAR` and `WAFFLE_JAVA` override the locations.
"""
from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.route import freerouting as fr

JAR_URL = f"https://github.com/freerouting/freerouting/releases/download/v{fr.VERSION}/freerouting-{fr.VERSION}.jar"
JDK_TAG = "jdk-25.0.4+7"
JDK_URL = ("https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.4%2B7/"
           "OpenJDK25U-jdk_x64_linux_hotspot_25.0.4_7.tar.gz")


def download(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-sSL", "--max-time", "900", "-o", str(out), "-w", "%{http_code}", url],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stdout.strip() != "200" or not out.is_file():
        raise SystemExit(f"download failed ({r.stdout.strip() or r.returncode}): {url}\n{r.stderr[-300:]}")


def fetch_jar() -> Path:
    jar = fr.jar_path()
    if not jar.is_file():
        print(f"fetching Freerouting {fr.VERSION} -> {jar}")
        download(JAR_URL, jar)
    return jar


def fetch_jdk() -> Path:
    jdk = fr.tools_dir() / "jdk"
    java = jdk / "bin" / "java"
    if java.is_file() and (fr.java_major(java) or 0) >= fr.JAVA_MAJOR:
        return java
    print(f"fetching Temurin {JDK_TAG} -> {jdk}")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "jdk.tar.gz"
        download(JDK_URL, archive)
        jdk.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            top = members[0].name.split("/")[0]
            for m in members:  # strip the top-level directory
                m.name = m.name[len(top) + 1:]
                if m.name:
                    tar.extract(m, jdk, filter="fully_trusted")
    return java


def main(argv: list[str]) -> int:
    if "--check" not in argv:
        jar = fetch_jar()
        java = fetch_jdk() if (fr.java_path() is None or (fr.java_major(fr.java_path()) or 0) < fr.JAVA_MAJOR) else fr.java_path()
        print(f"jar   {jar}")
        print(f"java  {java} (major {fr.java_major(java)})")
    reason = fr.available()
    print("freerouting:", "ok" if reason is None else reason)
    return 0 if reason is None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
