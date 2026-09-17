#!/usr/bin/env python3
"""Probe candidate reference repositories for KiCad boards (see waffle_eda/bench/survey.py).

    python3 scripts/survey_references.py owner/repo [owner/repo@branch ...] [--out build/survey.json]

Clones are shallow and blobless, kept under build/survey/ so a re-run is cheap.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import survey


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+")
    ap.add_argument("--out", default="build/survey.json")
    ap.add_argument("--work", default="build/survey")
    args = ap.parse_args(argv)
    survey.survey(args.specs, Path(args.work), Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
