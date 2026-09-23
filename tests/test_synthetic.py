"""Every synthetic case writes a board pcbnew reloads, with the stated layers and bus, clean DRC and only its open nets."""
import pytest

from waffle_eda.bench import harness, synthetic
from waffle_eda.kicad import board as kb


@pytest.mark.parametrize("name", sorted(synthetic.CASES))
def test_case_generates_and_passes_drc(name, tmp_path):
    case = synthetic.CASES[name]
    out = tmp_path / f"{name}.kicad_pcb"
    manifest = synthetic.make_bga_pair(case, out)
    b = kb.load_board(out)
    assert len(kb.copper_layers(b)) == case.layers
    assert len(manifest["bus"]) == case.bus_nets
    assert len(manifest["power"]) == case.power_balls
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    assert set(fps) == {"U1", "U2"}
    assert all(len(list(f.Pads())) == case.rows * case.cols for f in fps.values())
    facts = harness.drc_facts(harness.run_drc(out, tmp_path / f"{name}-drc.json"), set(manifest["bus"]))
    assert facts["electrical_total"] == 0
    assert len(facts["unconnected_bus_nets"]) == case.bus_nets


def test_orders_differ():
    straight = synthetic.make_bga_pair(synthetic.CASES["pair-6x6-straight"], pytest.importorskip("pathlib").Path("build/synthetic/t-straight.kicad_pcb"))
    reversed_ = synthetic.make_bga_pair(synthetic.CASES["pair-6x6-reversed"], pytest.importorskip("pathlib").Path("build/synthetic/t-reversed.kicad_pcb"))
    assert straight["bus"]["BUS00"]["U1"] == reversed_["bus"]["BUS00"]["U1"]
    assert straight["bus"]["BUS00"]["U2"] != reversed_["bus"]["BUS00"]["U2"]
