"""Parameter schema, ranges, enumerations, materials.

The ranges here are the single source of truth. The HTTP layer clamps incoming
values into them, the CLI defaults come from them, and the front end fetches
them to build its panel. There is no second copy in TypeScript.

A design is four independent axes multiplied together rather than a list of
pattern types: the cell field, the operation applied to it, the mask saying
where it lives, and the finish it is shown in.

`hole_shape` is not a fifth axis. It only says what a hole looks like once the
cell field has decided where it is and how big, so every other control keeps
working exactly as it did.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from typing import Any

_HEX = re.compile(r"[0-9a-f]*")

# --- materials ---------------------------------------------------------
# Colour is the cover's own colour; the interface borrows it as its accent.


@dataclass(frozen=True)
class Material:
    key: str
    label: str
    hex: str
    polymer: str
    density: float  # g/cm^3


MATERIALS: tuple[Material, ...] = (
    Material("teal", "Anodised Teal", "#17514C", "PETG", 1.27),
    Material("bone", "Bone", "#E3DDD0", "PLA", 1.24),
    Material("oxide", "Oxide", "#A8431E", "PLA", 1.24),
    Material("sulphur", "Sulphur", "#C9BE3C", "PETG", 1.27),
    Material("graphite", "Graphite", "#2B2E31", "PETG", 1.27),
    Material("ultramarine", "Ultramarine", "#2C3A8C", "PLA", 1.24),
    Material("clay", "Clay", "#C08575", "TPU", 1.21),
    Material("moss", "Moss", "#55603A", "TPU", 1.21),
)

MATERIALS_BY_KEY = {m.key: m for m in MATERIALS}

# --- enumerations -------------------------------------------------------

OPERATIONS = ("cut", "emboss", "engrave", "none")
HOLE_SHAPES = ("cells", "image")
RELIEF_PROFILES = ("dome", "ridge", "bevel")
MASK_MODES = ("full", "band", "panel", "stripes")
FINISHES = ("flat", "gradient", "faceted")

ENUMS: dict[str, tuple[str, ...]] = {
    "operation": OPERATIONS,
    "hole_shape": HOLE_SHAPES,
    "relief_profile": RELIEF_PROFILES,
    "mask_mode": MASK_MODES,
    "finish": FINISHES,
    "material": tuple(m.key for m in MATERIALS),
    "colour_b": tuple(m.key for m in MATERIALS),
}


# --- numeric ranges ----------------------------------------------------


@dataclass(frozen=True)
class Range:
    lo: float
    hi: float
    step: float
    unit: str = ""
    scale: str = "linear"
    """"log" lays the slider out by ratio, so 1.0 sits in the middle of a
    range that runs from a quarter to four times."""


RANGES: dict[str, Range] = {
    # limb
    "length": Range(300.0, 500.0, 1.0, "mm"),
    "knee_diameter": Range(60.0, 120.0, 1.0, "mm"),
    "ankle_diameter": Range(50.0, 90.0, 1.0, "mm"),
    "calf_bulge": Range(0.0, 30.0, 0.5, "mm"),
    "calf_position": Range(0.2, 0.8, 0.01, ""),
    "posterior_bias": Range(0.0, 1.0, 0.01, ""),
    # section
    "ovality": Range(0.75, 1.0, 0.01, ""),
    "section_squareness": Range(1.8, 3.5, 0.05, ""),
    "twist": Range(-30.0, 30.0, 1.0, "deg"),
    # shell
    "wall_thickness": Range(1.5, 4.0, 0.1, "mm"),
    # cell field
    "pattern_density": Range(0.0, 1.0, 0.01, ""),
    "density_gradient": Range(-1.0, 1.0, 0.01, ""),
    "irregularity": Range(0.0, 1.0, 0.01, ""),
    "anisotropy": Range(0.25, 4.0, 0.01, "", "log"),
    "flow_angle": Range(-60.0, 60.0, 1.0, "deg"),
    "corner_radius": Range(0.0, 1.0, 0.01, ""),
    # motif: the shape of the hole, once the cell has sized it
    "motif_fill": Range(0.3, 1.0, 0.01, ""),
    "motif_rotation": Range(0.0, 360.0, 1.0, "deg"),
    "motif_rotation_jitter": Range(0.0, 180.0, 1.0, "deg"),
    "motif_scale_jitter": Range(0.0, 0.5, 0.01, ""),
    "motif_smoothing": Range(0.0, 1.0, 0.01, ""),
    "threshold_bias": Range(-0.4, 0.4, 0.01, ""),
    # Floor is the schema's, not the printer's: a design saved against a fine
    # nozzle keeps its number and the generator widens it on a coarse one.
    "strut_width": Range(0.4, 4.0, 0.05, "mm"),
    # relief
    "relief_depth": Range(0.3, 4.0, 0.1, "mm"),
    # mask
    "mask_v_from": Range(0.0, 1.0, 0.01, ""),
    "mask_v_to": Range(0.0, 1.0, 0.01, ""),
    "mask_u_center": Range(0.0, 1.0, 0.01, ""),
    "mask_u_width": Range(0.05, 1.0, 0.01, ""),
    "mask_feather": Range(0.0, 0.5, 0.01, ""),
    # finish
    "facet_scale": Range(5.0, 40.0, 1.0, "mm"),
}


@dataclass
class CoverParams:
    # limb
    length: float = 380.0
    knee_diameter: float = 100.0
    ankle_diameter: float = 68.0
    calf_bulge: float = 14.0
    calf_position: float = 0.65
    posterior_bias: float = 0.75
    # section
    ovality: float = 0.88
    section_squareness: float = 2.3
    twist: float = 0.0
    # shell
    wall_thickness: float = 2.4
    # cell field
    pattern_density: float = 0.5
    density_gradient: float = 0.0
    irregularity: float = 0.7
    anisotropy: float = 1.0
    flow_angle: float = 0.0
    corner_radius: float = 0.15
    strut_width: float = 1.4
    # motif
    hole_shape: str = "cells"
    motif_id: str = ""
    """Digest of the picture held for this session. Empty means none."""
    motif_fill: float = 0.85
    motif_rotation: float = 0.0
    motif_rotation_jitter: float = 25.0
    motif_align_flow: bool = False
    motif_scale_jitter: float = 0.15
    motif_smoothing: float = 0.35
    threshold_bias: float = 0.0
    motif_invert: bool = False
    # operation
    operation: str = "cut"
    relief_depth: float = 1.5
    relief_profile: str = "dome"
    # mask
    mask_mode: str = "full"
    mask_v_from: float = 0.1
    mask_v_to: float = 0.9
    mask_u_center: float = 0.0
    mask_u_width: float = 0.35
    mask_mirror: bool = True
    mask_feather: float = 0.15
    # finish and output
    finish: str = "flat"
    material: str = "teal"
    colour_b: str = "bone"
    facet_scale: float = 22.0
    split_halves: bool = False
    seed: int = 7

    @property
    def material_spec(self) -> Material:
        return MATERIALS_BY_KEY.get(self.material, MATERIALS[0])

    @property
    def colour_b_spec(self) -> Material:
        return MATERIALS_BY_KEY.get(self.colour_b, MATERIALS[1])

    @property
    def cuts_through(self) -> bool:
        return self.operation == "cut"

    @property
    def uses_motif(self) -> bool:
        return self.hole_shape == "image" and bool(self.motif_id)

    @property
    def has_relief(self) -> bool:
        return self.operation in ("emboss", "engrave")

    def clamped(self) -> "CoverParams":
        """Return a copy with every value inside its declared range.

        Out-of-range input is a transport artefact, not a user decision, so it
        is silently corrected rather than reported.
        """
        data = asdict(self)
        for key, rng in RANGES.items():
            data[key] = float(min(max(float(data[key]), rng.lo), rng.hi))
        for key, allowed in ENUMS.items():
            if data[key] not in allowed:
                data[key] = allowed[0]
        for key in ("mask_mirror", "split_halves", "motif_align_flow", "motif_invert"):
            data[key] = bool(data[key])
        data["seed"] = int(data["seed"])
        # A digest names a picture the session is holding. Anything that is not
        # one names nothing, and the design falls back to cells.
        digest = str(data["motif_id"])[:64]
        data["motif_id"] = digest if _HEX.fullmatch(digest) else ""
        return CoverParams(**data)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CoverParams":
        raw = dict(raw)
        # `perforated` was the old on/off switch; it is now one of the
        # operations, and a saved design that still carries it still opens.
        if "perforated" in raw and not raw.pop("perforated"):
            raw.setdefault("operation", "none")
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known}).clamped()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def schema(min_strut: float | None = None) -> dict[str, Any]:
    """Everything the front end needs to build the panel.

    The strut slider starts at the printer's own minimum, so the panel cannot
    ask for a strut this machine will not lay down.
    """
    defaults = CoverParams()
    ranges = {
        k: {"lo": r.lo, "hi": r.hi, "step": r.step, "unit": r.unit, "scale": r.scale}
        for k, r in RANGES.items()
    }
    if min_strut is not None:
        ranges["strut_width"]["lo"] = min_strut
        defaults.strut_width = max(defaults.strut_width, min_strut)
    return {
        "ranges": ranges,
        "enums": {k: list(v) for k, v in ENUMS.items()},
        "defaults": defaults.to_dict(),
        "materials": [
            {
                "key": m.key,
                "label": m.label,
                "hex": m.hex,
                "polymer": m.polymer,
                "density": m.density,
            }
            for m in MATERIALS
        ],
    }
