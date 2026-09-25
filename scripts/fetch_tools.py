#!/usr/bin/env python3
"""Fetch the tools the pipeline needs that are not in the container image: Freerouting, the Java it runs
on, and KiCad's symbol and footprint libraries.

    python3 scripts/fetch_tools.py           # all of them, into build/tools/ (skipped when already there)
    python3 scripts/fetch_tools.py --check   # only say what is there

Freerouting 2.4.1 is compiled for Java 25 and the container has Java 21 (D56), so a Temurin JDK 25 goes next to
the jar. Both come from GitHub releases, which the egress policy allows; Maven Central and Adoptium's API do not
answer from here (measured 2026-09-23). `waffle_eda.route.freerouting` finds both under `build/tools/` and
`scripts/check_env.py` reports them. `WAFFLE_FREEROUTING_JAR` and `WAFFLE_JAVA` override the locations.

The container has KiCad's binaries and not its libraries (D74), which stages 2, 3 and 5 read: `kicad-symbols`
and `kicad-footprints` are shallow-cloned from KiCad's GitLab at the installed release's tag (`9.0.9`), which
the egress policy allows (measured 2026-09-24; GitHub's mirrors did not answer). `waffle_eda.kicad.libs` finds
them, or a copy installed with KiCad under /usr/share/kicad; `WAFFLE_KICAD_SYMBOLS` and `WAFFLE_KICAD_FOOTPRINTS`
override the locations.
"""
from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.kicad import libs
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


LIBRARIES = {"kicad-symbols": "https://gitlab.com/kicad/libraries/kicad-symbols.git",
             "kicad-footprints": "https://gitlab.com/kicad/libraries/kicad-footprints.git"}


def fetch_libraries() -> list[Path]:
    """KiCad's symbol and footprint libraries at the installed release's tag, under build/tools/."""
    tag = libs.kicad_release()
    out = []
    for name, url in LIBRARIES.items():
        dest = libs.tools_dir() / name
        if (dest / ".git").is_dir():
            out.append(dest)
            continue
        print(f"fetching {name} at {tag} -> {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", tag, url, str(dest)],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"clone failed: {url} at {tag}\n{r.stderr[-300:]}")
        out.append(dest)
    return out


def main(argv: list[str]) -> int:
    if "--check" not in argv:
        jar = fetch_jar()
        java = fetch_jdk() if (fr.java_path() is None or (fr.java_major(fr.java_path()) or 0) < fr.JAVA_MAJOR) else fr.java_path()
        print(f"jar   {jar}")
        print(f"java  {java} (major {fr.java_major(java)})")
        if libs.available():
            for d in fetch_libraries():
                print(f"libs  {d}")
    reason = fr.available()
    print("freerouting:", "ok" if reason is None else reason)
    missing = libs.available()
    print("kicad libraries:", f"ok ({libs.symbols_dir()}, {libs.footprints_dir()})" if missing is None else missing)
    return 0 if reason is None and missing is None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
