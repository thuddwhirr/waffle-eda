from waffle_eda.fab import profiles


def test_pcbway_profile_loads():
    p = profiles.load("pcbway")
    assert p.vendor == "PCBWay"
    assert p.supports_layers(8)
    assert not p.supports_layers(7)
    assert p.capability["min_track_outer_mm"] == 0.10
    assert "eight_layer_1p6mm" in p.stackups
    assert len(p.stackups["eight_layer_1p6mm"]["dielectrics"]) == 7


def test_unknown_price_returns_none_so_the_caller_escalates():
    p = profiles.load("pcbway")
    assert not p.price_known
    assert p.estimate_price(layers=8, area_mm2=100 * 160, quantity=5) is None


def test_available_lists_pcbway():
    assert "pcbway" in profiles.available()
