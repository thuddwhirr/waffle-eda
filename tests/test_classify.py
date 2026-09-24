"""Which group each bus net belongs to (D35, task 16). The groups decide what is matched against what, so a board
whose names the classifier does not know has no length criterion at all: every net of OrangeCrab fell into "other"
until this, and M3a reserved room for nothing because nothing was short of anything.

The three class C references write the same signals three ways, so the test is over all three vocabularies.
"""
import pytest

from waffle_eda.bench import bus_design as bd, references as refs
from waffle_eda.kicad import board as kb

pytestmark = pytest.mark.parked  # class B+/C machinery: not run until its class is reached (docs/plan.md)


CLASS_C = [r.key for r in refs.REFERENCES.values() if r.has_bus and r.cls == "C"]


@pytest.mark.parametrize("net,group,role,pair", [
    # ButterStick and LogicBone: DDR3_ prefix, _P/_N pairs, DQ for data
    ("/sheetRAM/DDR3_DQ0", "lane 0", "data", None),
    ("DDR3_DQ8", "lane 1", "data", None),
    ("DDR3_DQ15", "lane 1", "data", None),
    ("DDR3_LDQS_P", "lane 0", "strobe", "DQS0"),
    ("DDR3_UDQS_N", "lane 1", "strobe", "DQS1"),
    ("DDR3_LDM", "lane 0", "mask", None),
    ("DDR3_UDM", "lane 1", "mask", None),
    ("DDR3_CK0_P", "address/command", "clock", "CK0"),
    ("DDR3_CK1_N", "address/command", "clock", "CK1"),
    ("DDR3_A7", "address/command", "command", None),
    ("DDR3_BA1", "address/command", "command", None),
    ("DDR3_CKE0", "address/command", "command", None),
    ("DDR3_ODT1", "address/command", "command", None),
    ("DDR3_RST", "reset", "other", None),
    # OrangeCrab: RAM_ prefix, + and - pairs, D for data, # for the active-low command lines
    ("/DRAM/RAM_D0", "lane 0", "data", None),
    ("RAM_D8", "lane 1", "data", None),
    ("RAM_LDQS+", "lane 0", "strobe", "DQS0"),
    ("RAM_UDQS-", "lane 1", "strobe", "DQS1"),
    ("RAM_LDM", "lane 0", "mask", None),
    ("RAM_CK+", "address/command", "clock", "CK"),
    ("RAM_A15", "address/command", "command", None),
    ("RAM_BA2", "address/command", "command", None),
    ("RAM_CAS#", "address/command", "command", None),
    ("RAM_WE#", "address/command", "command", None),
    ("RAM_CS#", "address/command", "command", None),
    ("RAM_ODT", "address/command", "command", None),
    ("RAM_RESET#", "reset", "other", None),
])
def test_a_net_falls_in_its_group(net, group, role, pair):
    assert bd.classify(net) == (group, role, pair)


@pytest.mark.parametrize("key", CLASS_C)
def test_no_bus_net_of_a_reference_is_left_ungrouped(key):
    """Every net of a DDR3 bus is data, strobe, mask, clock, command or reset. One that is not is a name the
    classifier has never seen, and it silently drops out of every length criterion."""
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched")
    board = kb.load_board(refs.board_path(ref))
    other = sorted(bd.short_name(n) for n in kb.nets_matching(board, ref.bus_net_pattern)
                   if bd.classify(n)[0] == "other")
    assert not other, f"{key}: {len(other)} net(s) in no group: {', '.join(other)}"


@pytest.mark.parametrize("key", CLASS_C)
def test_every_reference_has_both_lanes_and_a_command_group(key):
    ref = refs.REFERENCES[key]
    if not refs.is_fetched(ref):
        pytest.skip(f"{key} is not fetched")
    board = kb.load_board(refs.board_path(ref))
    groups = {bd.classify(n)[0] for n in kb.nets_matching(board, ref.bus_net_pattern)}
    assert {"lane 0", "lane 1", "address/command"} <= groups, f"{key}: {sorted(groups)}"
