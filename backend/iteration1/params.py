"""Parameters of a cover built on the Rhino model.

The design axes are the transtibial ones, with the same ranges and the same
defaults, read from `backend.params` rather than copied: cell field, operation,
mask, finish, motif.  What is gone is every control that used to be the shape
of the cover, because the shape is the file.  What is left of the shape is the
wall, which the file also has an opinion about — the slider starts on the
thickness the model was drawn with — and how far the pattern keeps off the
rims.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from ..params import (
    _HEX,
    ENUMS,
    MATERIALS,
    MATERIALS_BY_KEY,
    RANGES,
    CoverParams,
    Material,
    Range,
)
from . import config as cfg
from .surface import Shape, _data

DESIGN_KEYS = (
    "pattern_density",
    "density_gradient",
    "irregularity",
    "anisotropy",
    "flow_angle",
    "corner_radius",
    "motif_fill",
    "motif_rotation",
    "motif_rotation_jitter",
    "motif_scale_jitter",
    "motif_smoothing",
    "threshold_bias",
    "strut_width",
    "relief_depth",
    "mask_v_from",
    "mask_v_to",
    "mask_u_center",
    "mask_u_width",
    "mask_feather",
    "facet_scale",
)

OWN_RANGES: dict[str, Range] = {
    "surface_smoothing": Range(0.0, 1.0, 0.01, ""),
    "rim_solid": Range(3.0, 30.0, 0.5, "mm"),
    # What the file's shape may be asked to do.  None of these draws a cover:
    # each one is a transformation of the one that was modelled, so the worst
    # a slider can do is wear it differently.
    "fullness": Range(0.85, 1.20, 0.01, ""),
    "ovality": Range(0.80, 1.25, 0.01, ""),
    "posterior_bias": Range(0.0, 1.0, 0.05, ""),
    "twist": Range(-20.0, 20.0, 1.0, "deg"),
    "height_scale": Range(0.85, 1.15, 0.01, ""),
    "top_trim": Range(0.0, 90.0, 1.0, "mm"),
    "bottom_trim": Range(0.0, 60.0, 1.0, "mm"),
    "notch_deepen": Range(0.0, 90.0, 1.0, "mm"),
    # The other covers stop at 4 mm, which is a wall for a shape they drew
    # themselves.  This one is drawn: the file has a 5.1 mm wall, and a range
    # that could not reach it would refuse the model on the way in.  The
    # curvature of the model still decides where the slider really stops, and
    # the generator reports it.
    "wall_thickness": Range(1.5, 8.0, 0.1, "mm"),
}

ITER_RANGES: dict[str, Range] = {**{k: RANGES[k] for k in DESIGN_KEYS}, **OWN_RANGES}

ITER_ENUMS = dict(ENUMS)

_BASE = CoverParams()


def modelled_wall(model: str | None = None) -> float:
    """The wall the Rhino model was drawn with, measured in preparation."""
    return float(_data(model).meta["wall_mm"])


@dataclass
class IterParams:
    # which modelled cover this is
    model: str = cfg.DEFAULT_MODEL
    """Key into `config.MODELS`.  Not a slider: it is which file the tab is
    showing, and a tab shows one."""

    # the model
    surface_smoothing: float = 0.0
    wall_thickness: float = 0.0
    """Zero means the wall the file came with; `clamped` fills it in."""
    rim_solid: float = cfg.RIM_SOLID
    # the shape, as worn
    fullness: float = 1.0
    ovality: float = 1.0
    posterior_bias: float = 0.0
    twist: float = 0.0
    height_scale: float = 1.0
    top_trim: float = 0.0
    bottom_trim: float = 0.0
    notch_deepen: float = 0.0
    # pattern: the transtibial defaults, unchanged
    pattern_density: float = _BASE.pattern_density
    density_gradient: float = _BASE.density_gradient
    irregularity: float = _BASE.irregularity
    anisotropy: float = _BASE.anisotropy
    flow_angle: float = _BASE.flow_angle
    corner_radius: float = _BASE.corner_radius
    strut_width: float = _BASE.strut_width
    hole_shape: str = _BASE.hole_shape
    motif_id: str = ""
    motif_fill: float = _BASE.motif_fill
    motif_rotation: float = _BASE.motif_rotation
    motif_rotation_jitter: float = _BASE.motif_rotation_jitter
    motif_align_flow: bool = _BASE.motif_align_flow
    motif_scale_jitter: float = _BASE.motif_scale_jitter
    motif_smoothing: float = _BASE.motif_smoothing
    threshold_bias: float = _BASE.threshold_bias
    motif_invert: bool = _BASE.motif_invert
    operation: str = _BASE.operation
    relief_depth: float = _BASE.relief_depth
    relief_profile: str = _BASE.relief_profile
    mask_mode: str = _BASE.mask_mode
    mask_v_from: float = _BASE.mask_v_from
    mask_v_to: float = _BASE.mask_v_to
    mask_u_center: float = _BASE.mask_u_center
    mask_u_width: float = _BASE.mask_u_width
    mask_mirror: bool = _BASE.mask_mirror
    mask_feather: float = _BASE.mask_feather
    finish: str = _BASE.finish
    material: str = _BASE.material
    colour_b: str = _BASE.colour_b
    facet_scale: float = _BASE.facet_scale
    seed: int = _BASE.seed

    # --- the same conveniences the other covers offer --------------------
    @property
    def material_spec(self) -> Material:
        return MATERIALS_BY_KEY.get(self.material, MATERIALS[0])

    @property
    def colour_b_spec(self) -> Material:
        return MATERIALS_BY_KEY.get(self.colour_b, MATERIALS[1])

    @property
    def shape(self) -> Shape:
        """The knobs that move the modelled surface, as one value.

        The surface is cached on it, so a design that only changes the pattern
        re-reads the same shaped surface rather than building it again.
        """
        return Shape(
            fullness=self.fullness,
            ovality=self.ovality,
            posterior_bias=self.posterior_bias,
            twist=self.twist,
            height_scale=self.height_scale,
            top_trim=self.top_trim,
            bottom_trim=self.bottom_trim,
            notch_deepen=self.notch_deepen,
        )

    @property
    def cuts_through(self) -> bool:
        return self.operation == "cut"

    @property
    def uses_motif(self) -> bool:
        return self.hole_shape == "image" and bool(self.motif_id)

    @property
    def has_relief(self) -> bool:
        return self.operation in ("emboss", "engrave")

    def clamped(self) -> IterParams:
        data = asdict(self)
        if data.get("model") not in cfg.MODELS:
            data["model"] = cfg.DEFAULT_MODEL
        if float(data["wall_thickness"]) <= 0.0:
            data["wall_thickness"] = modelled_wall(data["model"])
        for key, rng in ITER_RANGES.items():
            data[key] = float(min(max(float(data[key]), rng.lo), rng.hi))
        for key, allowed in ITER_ENUMS.items():
            if data[key] not in allowed:
                data[key] = allowed[0]
        for key in ("mask_mirror", "motif_align_flow", "motif_invert"):
            data[key] = bool(data[key])
        data["seed"] = int(data["seed"])
        digest = str(data["motif_id"])[:64]
        data["motif_id"] = digest if _HEX.fullmatch(digest) else ""
        return type(self)(**data)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> IterParams:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in dict(raw).items() if k in known}).clamped()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def schema(min_strut: float | None = None, model: str | None = None) -> dict[str, Any]:
    defaults = IterParams().clamped()
    ranges = {
        k: {"lo": r.lo, "hi": r.hi, "step": r.step, "unit": r.unit, "scale": r.scale}
        for k, r in ITER_RANGES.items()
    }
    if min_strut is not None:
        ranges["strut_width"]["lo"] = min_strut
        defaults.strut_width = max(defaults.strut_width, min_strut)
    return {
        "ranges": ranges,
        "enums": {k: list(v) for k, v in ITER_ENUMS.items()},
        "defaults": defaults.to_dict(),
        "materials": [
            {"key": m.key, "label": m.label, "hex": m.hex, "polymer": m.polymer, "density": m.density}
            for m in MATERIALS
        ],
        "model": _data(model).meta,
    }
