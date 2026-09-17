"""Registry consistency runs always; measurements run only when the reference boards are fetched."""
import re

import pytest

from waffle_eda.bench import references as refs


def test_registry_is_consistent():
    for key, ref in refs.REFERENCES.items():
        assert ref.key == key
        assert len(ref.commit) == 40
        re.compile(ref.bus_net_pattern)
        assert ref.licence.startswith("CERN OHL")
        assert refs.checkout_dir(ref).name in ("butterstick", "logicbone")


@pytest.mark.parametrize("key", ["butterstick", "logicbone"])
def test_measure_reference(key):
    """The measurement reproduces the registry's recorded facts; the physics claims live in the M1 report."""
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} not fetched; run scripts/fetch_references.py")
    data = refs.measure(ref)
    bus = data["bus"]
    assert len(data["copper_layers"]) == 8
    assert bus["net_count"] == ref.bus_net_count
    assert bus["routed_net_count"] == bus["net_count"]
    # The brief's measured claim: layer changes happen at the dog-bone vias under the packages.
    assert bus["vias_in_packages"] >= 0.95 * bus["vias_total"]
    assert bus["length_mm"]["max"] < 60
    for r in ref.dram_refs:
        assert r in data["packages"]
