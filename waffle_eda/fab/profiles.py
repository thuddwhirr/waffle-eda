"""Load a fab profile from ``profiles/<name>.toml``.

A profile carries the vendor's capability (the limits every design rule must stay within), its standard stack-ups
with dielectric data, and a price model. Price is a number or it is unknown; when it is unknown, any decision that
depends on cost escalates to the owner (definition, section 4).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

REQUIRED_CAPABILITY_KEYS = (
    "layer_counts",
    "min_track_outer_mm",
    "min_clearance_outer_mm",
    "min_track_inner_mm",
    "min_clearance_inner_mm",
    "min_drill_mm",
    "min_annular_ring_mm",
    "standard_via_pad_mm",
    "standard_via_drill_mm",
    "hole_clearance_mm",
    "copper_to_edge_mm",
    "via_in_pad",
    "filled_capped_vias",
    "controlled_impedance",
)


@dataclass(frozen=True)
class FabProfile:
    name: str
    vendor: str
    source: str
    capability: dict
    stackups: dict
    price: dict

    @property
    def price_known(self) -> bool:
        return self.price.get("status") == "known"

    def estimate_price(self, layers: int, area_mm2: float, quantity: int, **options) -> float | None:
        """Board price, or None when the profile has no captured price model (the caller must escalate)."""
        if not self.price_known:
            return None
        raise NotImplementedError("price model not defined yet; capture real quotes first (decision D5)")

    def supports_layers(self, layers: int) -> bool:
        return layers in self.capability["layer_counts"]


def available() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.toml"))


def load(name: str) -> FabProfile:
    path = PROFILES_DIR / f"{name}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"no fab profile named {name!r}; available: {available()}")
    data = tomllib.loads(path.read_text())
    missing = [k for k in REQUIRED_CAPABILITY_KEYS if k not in data.get("capability", {})]
    if missing:
        raise ValueError(f"fab profile {name}: capability is missing {missing}")
    return FabProfile(
        name=data["profile"]["name"],
        vendor=data["profile"]["vendor"],
        source=data["profile"]["source"],
        capability=data["capability"],
        stackups=data.get("stackup", {}),
        price=data.get("price", {"status": "unknown"}),
    )
