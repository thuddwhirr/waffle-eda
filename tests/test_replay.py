"""Every gate row replayed from its frozen router session (`bench.replay`, D147): the row as `scripts/gate.py` runs
it, minutes a board, the same board every time, with the router's output held still so that whatever these tests
see is our export and finishing. `pytest -m replay` runs them; a fresh container needs the references and tools
(docs/plan.md, "Confirm the state first").

The invariant: the finishing (the repair, the pours, the fill, the stitching) never parts two pads the router
joined. D144 and D145 were each found in hours of router time; replayed on the code before them, this test fails on
buspirate5-rev10 and sensor-watch-c1 in two minutes. The target: the row passes its class's criterion.
"""
import os
import sys

import pytest

from waffle_eda.bench import rebuild, references as refs, replay
from waffle_eda.kicad import board as kb

sys.path.insert(0, str(refs.repo_root() / "scripts"))

pytestmark = pytest.mark.replay
KEYS = replay.frozen_keys()
_ROWS: dict[str, tuple[bool, str]] = {}


def _replayed(key: str) -> tuple[bool, str]:
    """The row replayed once per test run: (verdict, detail)."""
    if key not in _ROWS:
        import gate
        ref = refs.REFERENCES[key]
        if not refs.is_fetched(ref):
            pytest.skip(f"{key} is not fetched; run scripts/fetch_references.py")
        defaults = gate.CLASS_B if replay.manifest(key)["row"]["gate"] == "b" else gate.CLASS_A
        before = os.environ.get("WAFFLE_REPLAY")
        os.environ["WAFFLE_REPLAY"] = "1"
        try:
            [(_key, verdict, detail)] = gate._reroute_gate([ref], defaults)
        finally:
            if before is None:
                del os.environ["WAFFLE_REPLAY"]
            else:
                os.environ["WAFFLE_REPLAY"] = before
        _ROWS[key] = (verdict, detail)
    return _ROWS[key]


def test_every_class_row_has_a_frozen_session():
    assert set(KEYS) >= {"tinkerforge-temperature", "open-book-c1", "olimex-esp32c3-devkit", "olimex-rp2040-pico-pc",
                         "libresolar-mppt-2420", "upduino-v3.01", "pico-ice-rev3", "sensor-watch-c1",
                         "tinkerforge-master-v3.2", "buspirate5-rev10", "olimex-esp32-poe-m1", "tinytapeout-demo"}


@pytest.mark.parametrize("key", KEYS)
def test_the_finishing_never_parts_pads_the_router_joined(key):
    _verdict, detail = _replayed(key)
    assert "StaleSession" not in detail, detail
    ref = refs.REFERENCES[key]
    imported = kb.load_board(refs.repo_root() / "build" / "fr" / key / "imported.kicad_pcb")
    final = kb.load_board(rebuild.problem_path(ref).with_name(f"{key}-routed.kicad_pcb"))
    names = kb.pad_names(final)
    after = kb.pad_pieces(final)
    parted = []
    for net, groups in kb.pad_pieces(imported).items():
        for group in groups:
            pieces = [g for g in after.get(net, []) if g & group]
            if len(pieces) > 1:
                parted.append(f"{net}: " + " / ".join(",".join(sorted(names.get(u, u) for u in g & group))
                                                      for g in pieces))
    assert not parted, parted


@pytest.mark.parametrize("key", KEYS)
def test_every_plated_pad_left_to_a_plane_is_reached_by_its_fill(key):
    """The router takes a plated pad of a plane's net that passes through the plane's layer as joined by it; the
    check before the export (`route.planes.unreached`) lists those the fill does not reach (D147)."""
    import json
    _replayed(key)
    row = json.loads((refs.repo_root() / "build" / "fr" / key / "row.json").read_text())
    assert row["unreached"] == [], row["unreached"]


@pytest.mark.parametrize("key", KEYS)
def test_the_row_passes_its_class(key):
    verdict, detail = _replayed(key)
    assert verdict, detail
