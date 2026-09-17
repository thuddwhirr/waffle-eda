"""Registry consistency runs always; measurements and the harness run only for fetched boards."""
import re

import pytest

from waffle_eda.bench import harness, references as refs


def test_registry_is_consistent():
    assert len(refs.REFERENCES) >= 20
    for key, ref in refs.REFERENCES.items():
        assert ref.key == key
        assert ref.cls in refs.CLASSES
        assert re.fullmatch(r"[0-9a-f]{40}", ref.commit)
        assert ref.board.endswith(".kicad_pcb")
        assert ref.licence and ref.attribution
        assert ref.key_parts, key
        if ref.has_bus:
            re.compile(ref.bus_net_pattern)
            assert ref.bus_parts, key
        else:
            assert not ref.bus_parts, key


def test_every_class_has_references():
    for cls in refs.CLASSES:
        assert refs.by_class(cls), cls


@pytest.mark.parametrize("key", sorted(refs.REFERENCES))
def test_measure_reference(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} not fetched; run scripts/fetch_references.py")
    data = refs.measure(ref)
    assert len(data["copper_layers"]) >= 2
    assert data["footprints"] > 0
    for part in (*ref.key_parts, *ref.bus_parts):
        assert part in data["packages"]
    if ref.has_bus:
        bus = data["bus"]
        if ref.bus_net_count is not None:
            assert bus["net_count"] == ref.bus_net_count
        assert bus["routed_net_count"] == bus["net_count"]


@pytest.mark.parametrize("key", ["butterstick", "logicbone"])
def test_ddr3_references_match_the_brief(key):
    """The brief's measured claims: layer changes at the packages, three or fewer vias on most nets."""
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} not fetched")
    bus = refs.measure(ref)["bus"]
    assert len(refs.measure(ref)["copper_layers"]) == 8
    assert bus["vias_in_packages"] >= 0.95 * bus["vias_total"]
    assert bus["length_mm"]["max"] < 60


@pytest.mark.parametrize("key", ["butterstick", "logicbone"])
def test_harness_do_nothing_scores_zero_and_answer_passes(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} not fetched")
    problem, removed = harness.strip_bus(ref)
    assert removed["bus_nets"] == ref.bus_net_count
    nothing = harness.score(ref, problem)
    assert nothing.connected == 0 and nothing.score == 0.0 and not nothing.passed
    answer = harness.score(ref, refs.board_path(ref))
    assert answer.passed and answer.connected == answer.bus_nets and answer.score >= 0.95
