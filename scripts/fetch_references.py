#!/usr/bin/env python3
"""Fetch the reference boards (CERN OHL v1.2, see waffle_eda/bench/references.py for attribution) into references/.

    python3 scripts/fetch_references.py            # all
    python3 scripts/fetch_references.py logicbone  # one or more keys
"""
from __future__ import annotations

import sys

import _path  # noqa: F401
from waffle_eda.bench import references as refs


def main(argv: list[str]) -> int:
    keys = argv or list(refs.REFERENCES)
    for key in keys:
        ref = refs.REFERENCES[key]
        path = refs.fetch(ref)
        print(f"{ref.key:<18} {ref.licence:<14} {ref.commit[:12]}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
