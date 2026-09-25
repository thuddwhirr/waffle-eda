"""The S-expression reader and writer, the symbol reader and the library lookup that stages 2, 3 and 5 rely on
(`kicad/sexp.py`, `kicad/symbols.py`, `kicad/libs.py`; ported from the salvage under D4, so tested here)."""
import pytest

from waffle_eda.kicad import libs, symbols
from waffle_eda.kicad.sexp import Sym, dumps, find, findall, loads, value

TEXT = '(kicad_sch (version 20250114) (paper "A4") (text "a \\"quoted\\" word" (at 1.5 2 0)) (yes) (list (a) (b 2)))'


def test_the_reader_keeps_symbols_strings_and_nesting_apart():
    doc = loads(TEXT)
    assert doc[0] == "kicad_sch" and isinstance(doc[0], Sym)
    assert value(doc, "version") == "20250114" and isinstance(value(doc, "version"), Sym)
    assert value(doc, "paper") == "A4" and not isinstance(value(doc, "paper"), Sym)
    assert find(doc, "text")[1] == 'a "quoted" word'
    assert [x[0] for x in findall(find(doc, "list"), "a")] == ["a"]
    assert find(doc, "missing") is None and value(doc, "missing", 7) == 7


def test_what_is_written_reads_back_the_same():
    doc = loads(TEXT)
    again = loads(dumps(doc))
    assert again == doc
    assert dumps([Sym("at"), 1.5, 2, 0]) == "(at 1.5 2 0)"
    assert dumps([Sym("q"), 'say "hi"']) == '(q "say \\"hi\\"")'
    assert dumps([Sym("p"), [Sym("a"), 1], [Sym("b"), 2]]) == "(p\n\t(a 1)\n\t(b 2)\n)"


def test_unbalanced_text_is_an_error():
    with pytest.raises(ValueError):
        loads("(a (b)")
    with pytest.raises(ValueError):
        loads("(a))")


def _need_libs():
    if libs.available():
        pytest.skip(libs.available())


def test_a_symbol_is_read_with_its_pins_by_number_and_name():
    _need_libs()
    sym = symbols.get_symbol("Sensor_Temperature:TMP102xxDRL")
    assert symbols.property_value(sym, "Footprint") == "Package_TO_SOT_SMD:SOT-563"
    assert symbols.property_value(sym, "Datasheet").startswith("http")
    pins = {p["number"]: p for p in symbols.pins(sym)}
    assert set(pins) == {"1", "2", "3", "4", "5", "6"}
    assert pins["6"]["name"] == "SDA" and pins["6"]["type"] == "bidirectional"
    assert symbols.resolve_pin(sym, "V+") == "5" and symbols.resolve_pin(sym, "2") == "2"
    with pytest.raises(KeyError):
        symbols.resolve_pin(sym, "VCC")
    assert not symbols.is_power(sym) and symbols.is_power(symbols.get_symbol("power:GND"))


def test_a_derived_symbol_is_flattened_over_its_parent():
    """`Device:C_Small` and the like derive from a parent with ``extends``; the copy stage 3 writes into the
    schematic must carry the parent's pins and graphics under the child's name."""
    _need_libs()
    lib = symbols.load_library(libs.symbol_file("Device"))
    derived = [s[1] for s in findall(lib, "symbol") if find(s, "extends")]
    assert derived, "Device.kicad_sym has derived symbols"
    sym = symbols.get_symbol(f"Device:{derived[0]}")
    assert find(sym, "extends") is None
    assert symbols.pins(sym), "the parent's pins are carried"
    assert all(u[1].startswith(derived[0]) for u in findall(sym, "symbol"))


def test_the_library_lookup_names_what_is_missing():
    _need_libs()
    assert libs.has_footprint("Package_TO_SOT_SMD:SOT-563")
    assert not libs.has_footprint("Package_TO_SOT_SMD:SOT-5630")
    assert not libs.has_footprint("NoSuchLib:X")
    assert libs.has_symbol("Device:R") and not libs.has_symbol("Device:R_nope") and not libs.has_symbol("Nope:R")
    with pytest.raises(ValueError):
        libs.split_id("noseparator")
    fp = libs.load_footprint("Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical")
    assert len(list(fp.Pads())) == 4
