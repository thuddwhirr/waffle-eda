"""Read how a reference routes its bus (waffle_eda.bench.bus_design) and print the report; JSON to build/."""
import json
import sys
from pathlib import Path

import _path  # noqa: F401
from waffle_eda.bench import bus_design

keys = sys.argv[1:] or ["butterstick", "logicbone"]
for key in keys:
    d = bus_design.measure_bus_design(key)
    out = Path("build") / f"bus-design-{key}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(d, indent=1, default=lambda o: dict(o) if hasattr(o, "items") else str(o)))
    print(bus_design.report(d))
    print(f"   written {out}")
