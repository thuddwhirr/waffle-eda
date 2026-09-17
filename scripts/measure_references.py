#!/usr/bin/env python3
"""Measure the fetched reference boards; write build/measure-<key>.json and print one summary line each.

    python3 scripts/measure_references.py            # all fetched
    python3 scripts/measure_references.py logicbone  # one or more keys
"""
from __future__ import annotations

import json
import sys

import _path  # noqa: F401
from waffle_eda.bench import references as refs


def main(argv: list[str]) -> int:
    keys = argv or list(refs.REFERENCES)
    rc = 0
    for key in keys:
        ref = refs.REFERENCES[key]
        if not refs.is_fetched(ref):
            print(f"{ref.key:<18} not fetched (run scripts/fetch_references.py)")
            rc = 1
            continue
        path = refs.write_measurement(ref)
        data = json.loads(path.read_text())
        print(refs.summary_line(data))
        print(f"{'':<18} -> {path}")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
