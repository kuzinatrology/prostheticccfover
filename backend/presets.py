"""Named starting points.

A preset is nothing but a set of slider positions. Choosing one moves the
sliders and then gets out of the way: every control stays live, so a preset is
somewhere to start from rather than a mode to be in. That is the whole product
idea, and it is why a preset is a plain dictionary and not a type.

They live here rather than in the front end so the tests can build and export
every one of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .params import CoverParams


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    note: str
    values: dict[str, Any]

    def params(self, base: CoverParams | None = None) -> CoverParams:
        data = (base or CoverParams()).to_dict()
        data.update(self.values)
        return CoverParams.from_dict(data)


PRESETS: tuple[Preset, ...] = (
    Preset(
        "lattice",
        "Lattice",
        "Open cells, evenly scattered",
        dict(
            operation="cut",
            irregularity=0.7,
            anisotropy=1.0,
            flow_angle=0.0,
            corner_radius=0.15,
            mask_mode="full",
            pattern_density=0.5,
            strut_width=1.4,
            finish="flat",
        ),
    ),
    Preset(
        "chevron",
        "Chevron",
        "Long cells leaning across the shin",
        dict(
            operation="cut",
            anisotropy=0.35,
            flow_angle=35.0,
            corner_radius=0.9,
            strut_width=3.0,
            irregularity=0.3,
            mask_mode="full",
            pattern_density=0.45,
            finish="flat",
        ),
    ),
    Preset(
        "scales",
        "Scales",
        "Raised domes, no holes",
        dict(
            operation="emboss",
            relief_profile="dome",
            relief_depth=1.6,
            anisotropy=0.55,
            irregularity=0.15,
            mask_mode="full",
            pattern_density=0.55,
            finish="flat",
        ),
    ),
    Preset(
        "vent",
        "Vent",
        "Perforated panels front and back",
        dict(
            operation="cut",
            mask_mode="panel",
            mask_mirror=True,
            mask_feather=0.25,
            mask_u_width=0.35,
            mask_u_center=0.0,
            anisotropy=0.4,
            pattern_density=0.8,
            corner_radius=0.4,
            finish="flat",
        ),
    ),
    Preset(
        "facet",
        "Facet",
        "Smooth shell, shaded low-poly",
        dict(
            operation="none",
            finish="faceted",
            facet_scale=22.0,
        ),
    ),
    Preset(
        "ridge",
        "Ridge",
        "Grooves sunk along the cell walls",
        dict(
            operation="engrave",
            relief_profile="ridge",
            relief_depth=1.2,
            anisotropy=0.6,
            flow_angle=20.0,
            irregularity=0.5,
            mask_mode="full",
            finish="flat",
        ),
    ),
)

PRESETS_BY_KEY = {p.key: p for p in PRESETS}


def as_json() -> list[dict[str, Any]]:
    return [
        {"key": p.key, "label": p.label, "note": p.note, "values": p.values}
        for p in PRESETS
    ]
