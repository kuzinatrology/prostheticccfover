"""Parameters of a transfemoral cover.

The design axes are the transtibial ones, with the same ranges and the same
defaults, read from `backend.params` rather than copied: cell field, operation,
mask, finish, motif. What is gone is everything that used to be the shape of
the leg, because the shape is the scan. What is new is the smoothing of that
scan and the attachment: the seam, the magnets and the two clamps.

Several ranges here move with the geometry. The generator reports where each
one stops, the way it already does for the wall, and the panel shortens the
track to match.
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
from ..printer_profile import DEFAULT_PROFILE
from . import config as cfg

DESIGN_KEYS = (
    "wall_thickness",
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

CL = DEFAULT_PROFILE.CLEARANCE

# The hole's corners are rounded to MIN_STRUT and the module's are square: a
# rounded corner clears a square one only once the sides stand this much off.
CORNER_ROOM = 2.0 * (1.0 - 2.0**-0.5) * DEFAULT_PROFILE.MIN_STRUT
UPPER_MIN_WIDTH = round(cfg.UPPER_HOLE_WIDTH + CL + CORNER_ROOM + 0.05, 1)
UPPER_MIN_DEPTH = round(cfg.UPPER_HOLE_DEPTH + CL + CORNER_ROOM + 0.05, 1)

MOUNT_RANGES: dict[str, Range] = {
    "surface_smoothing": Range(0.0, 1.0, 0.01, ""),
    "seam_offset": Range(0.0, 60.0, 0.5, "mm"),
    "seam_solid_width": Range(4.0, 30.0, 0.5, "mm"),
    "magnet_diameter": Range(3.0, 12.0, 0.5, "mm"),
    "magnet_height": Range(1.0, 6.0, 0.5, "mm"),
    "magnet_count": Range(1.0, 8.0, 1.0, ""),
    "lower_clamp_z": Range(-300.0, 100.0, 1.0, "mm"),
    "upper_clamp_z": Range(-300.0, 100.0, 1.0, "mm"),
    "lower_hole_diameter": Range(20.0, 45.0, 0.1, "mm"),
    "upper_hole_width": Range(40.0, 90.0, 0.5, "mm"),
    "upper_hole_depth": Range(40.0, 90.0, 0.5, "mm"),
    "bolt_diameter": Range(3.0, 6.5, 0.1, "mm"),
    "leaf_count": Range(1.0, 7.0, 1.0, ""),
    "leaf_size": Range(30.0, 110.0, 1.0, "mm"),
    "leaf_tilt": Range(0.0, 45.0, 1.0, "deg"),
}

TF_RANGES: dict[str, Range] = {**{k: RANGES[k] for k in DESIGN_KEYS}, **MOUNT_RANGES}

TF_ENUMS = {k: v for k, v in ENUMS.items()}

_BASE = CoverParams()


@dataclass
class TFParams:
    # scan
    surface_smoothing: float = cfg.SMOOTH_DEFAULT
    # shell and pattern: the transtibial defaults, unchanged
    wall_thickness: float = _BASE.wall_thickness
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
    # attachment
    seam_offset: float = 0.0
    seam_solid_width: float = 12.0
    magnet_diameter: float = 6.0
    magnet_height: float = 3.0
    magnet_count: float = 4.0
    lower_clamp_z: float = -225.0
    upper_clamp_z: float = -60.0
    lower_hole_diameter: float = round(cfg.PYLON_DIAMETER + CL, 1)
    upper_hole_width: float = cfg.UPPER_HOLE_WIDTH + CL + cfg.PRELIMINARY_MARGIN
    upper_hole_depth: float = cfg.UPPER_HOLE_DEPTH + CL + cfg.PRELIMINARY_MARGIN
    bolt_diameter: float = 4.5
    # leaves on the back half
    back_leaves: bool = False
    leaf_count: float = 3.0
    leaf_size: float = 70.0
    leaf_tilt: float = 20.0

    # --- the same conveniences the transtibial parameters offer ----------
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

    @property
    def magnets(self) -> int:
        return int(round(self.magnet_count))

    def clamped(self) -> TFParams:
        data = asdict(self)
        for key, rng in TF_RANGES.items():
            data[key] = float(min(max(float(data[key]), rng.lo), rng.hi))
        for key, allowed in TF_ENUMS.items():
            if data[key] not in allowed:
                data[key] = allowed[0]
        for key in ("mask_mirror", "motif_align_flow", "motif_invert", "back_leaves"):
            data[key] = bool(data[key])
        data["seed"] = int(data["seed"])
        data["magnet_count"] = float(round(data["magnet_count"]))
        data["leaf_count"] = float(round(data["leaf_count"]))
        # The pipe and the module go through these holes: never tighter than
        # the part plus the fitting gap.
        data["lower_hole_diameter"] = max(data["lower_hole_diameter"], cfg.PYLON_DIAMETER + CL)
        data["upper_hole_width"] = max(data["upper_hole_width"], UPPER_MIN_WIDTH)
        data["upper_hole_depth"] = max(data["upper_hole_depth"], UPPER_MIN_DEPTH)
        digest = str(data["motif_id"])[:64]
        data["motif_id"] = digest if _HEX.fullmatch(digest) else ""
        return TFParams(**data)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TFParams:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in dict(raw).items() if k in known}).clamped()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def schema(min_strut: float | None = None) -> dict[str, Any]:
    defaults = TFParams()
    ranges = {
        k: {"lo": r.lo, "hi": r.hi, "step": r.step, "unit": r.unit, "scale": r.scale}
        for k, r in TF_RANGES.items()
    }
    if min_strut is not None:
        ranges["strut_width"]["lo"] = min_strut
        defaults.strut_width = max(defaults.strut_width, min_strut)
    ranges["lower_hole_diameter"]["lo"] = round(cfg.PYLON_DIAMETER + CL, 1)
    ranges["upper_hole_width"]["lo"] = UPPER_MIN_WIDTH
    ranges["upper_hole_depth"]["lo"] = UPPER_MIN_DEPTH
    return {
        "ranges": ranges,
        "enums": {k: list(v) for k, v in TF_ENUMS.items()},
        "defaults": defaults.to_dict(),
        "materials": [
            {"key": m.key, "label": m.label, "hex": m.hex, "polymer": m.polymer, "density": m.density}
            for m in MATERIALS
        ],
    }
