"""The anatomic cover, as a tab.

The shape is not drawn by sliders. `anatomic/` measures it: stage 4 leaves the
cover as a radius over angle and height about a centre line, sized to clear the
prosthesis, shaped like a human shank, cut by a rim curve. What is left to
decide here is how much room the prosthesis gets and where the rim runs.

Everything past that is the same cover as the other two tabs. The measured
skin is wrapped as a `SurfaceBase` and handed to the ordinary generator, so
the cell field, the operation, the mask and the finish all work on it
unchanged — no second pipeline, and a preset means the same thing here as it
does below the knee.

The flexion check rides along with every build, because on this cover it is
not a detail: the notch that lets the knee reach 130 degrees is most of what
the top of the shape is.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import numpy as np
import trimesh

from anatomic import config as anat
from anatomic import reference as anat_ref
from anatomic import stage4_surface, stage5_flexion

from . import anatomic_leaves as lv
from .anatomic_surface import AnatomicSurface
from .generator import DRAFT, FINAL, Cover, generate
from .params import RANGES as BASE_RANGES
from .params import CoverParams
from .params import schema as base_schema
from .presets import as_json as presets_json
from .printer_profile import DEFAULT_PROFILE

# The handles this cover has of its own, on top of the shared pattern ones.
SHAPE_RANGES: dict[str, dict[str, Any]] = {
    "clearance": {"lo": 2.0, "hi": 15.0, "step": 0.5, "unit": "mm"},
    "fullness": {"lo": 0.85, "hi": 1.35, "step": 0.01, "unit": ""},
    "knee_cover": {"lo": -60.0, "hi": 85.0, "step": 2.0, "unit": "mm"},
    "flexion": {"lo": 60.0, "hi": 130.0, "step": 5.0, "unit": "deg"},
    "bottom_clearance": {"lo": 0.0, "hi": 60.0, "step": 1.0, "unit": "mm"},
    "leaf_count": {"lo": 1.0, "hi": 7.0, "step": 1.0, "unit": ""},
    "leaf_size": {"lo": 30.0, "hi": 110.0, "step": 1.0, "unit": "mm"},
    "leaf_tilt": {"lo": 0.0, "hi": 45.0, "step": 1.0, "unit": "deg"},
}

REF_RANGES: dict[str, dict[str, Any]] = {
    "clearance": SHAPE_RANGES["clearance"],
    "fullness": SHAPE_RANGES["fullness"],
    "bottom_clearance": SHAPE_RANGES["bottom_clearance"],
    "seat_z": {"lo": -200.0, "hi": 0.0, "step": 2.0, "unit": "mm"},
    "flexion": {"lo": 60.0, "hi": 130.0, "step": 5.0, "unit": "deg"},
    "notch_deepen": {"lo": 0.0, "hi": 120.0, "step": 2.0, "unit": "mm"},
    "leaf_count": SHAPE_RANGES["leaf_count"],
    "leaf_size": SHAPE_RANGES["leaf_size"],
    "leaf_tilt": SHAPE_RANGES["leaf_tilt"],
}

REF_DEFAULTS: dict[str, Any] = {
    "clearance": anat.CLEARANCE_MM,
    "fullness": anat.COVER_FULLNESS,
    "bottom_clearance": anat.BOTTOM_CLEARANCE_MM,
    "seat_z": anat.REFERENCE_TOP_Z,
    "flexion": anat.FLEXION_MAX,
    "notch_deepen": anat.REFERENCE_DEEPEN_MM,
    "back_leaves": False,
    "leaf_count": 3.0,
    "leaf_size": 70.0,
    "leaf_tilt": 20.0,
}

SHAPE_DEFAULTS: dict[str, Any] = {
    "clearance": anat.CLEARANCE_MM,
    "fullness": anat.COVER_FULLNESS,
    "knee_cover": anat.COVER_TOP_Z,
    "flexion": anat.FLEXION_MAX,
    "bottom_clearance": anat.BOTTOM_CLEARANCE_MM,
    "back_leaves": False,
    "leaf_count": 3.0,
    "leaf_size": 70.0,
    "leaf_tilt": 20.0,
}

# The limb and section sliders are gone: the leg is measured, not drawn. Their
# values still have to be something the shared parameter object accepts.
HIDDEN = (
    "length", "knee_diameter", "ankle_diameter", "calf_bulge", "calf_position",
    "posterior_bias", "ovality", "section_squareness", "twist", "split_halves",
)

DRAFT_ROWS = 96
FINAL_ROWS = anat.COVER_ROWS


def schema(from_reference: bool = False) -> dict[str, Any]:
    """The shared schema with the limb gone and the shape handles added."""
    ranges = REF_RANGES if from_reference else SHAPE_RANGES
    defaults = REF_DEFAULTS if from_reference else SHAPE_DEFAULTS
    out = base_schema(min_strut=DEFAULT_PROFILE.MIN_STRUT)
    out["ranges"] = {k: v for k, v in out["ranges"].items() if k not in HIDDEN} | {
        k: {**v, "scale": "linear"} for k, v in ranges.items()
    }
    out["defaults"] = dict(out["defaults"]) | defaults
    out["defaults"]["wall_thickness"] = anat.WALL_THICKNESS_MM
    out["profile"] = {
        "name": DEFAULT_PROFILE.name,
        "min_strut": DEFAULT_PROFILE.MIN_STRUT,
        "min_hole": DEFAULT_PROFILE.MIN_HOLE,
        "clearance": DEFAULT_PROFILE.CLEARANCE,
    }
    out["enums"] = dict(out["enums"])
    out["formats"] = ["3mf", "stl"]
    out["presets"] = presets_json()
    return out


def _clamp(params: dict[str, Any], key: str, from_reference: bool = False) -> float:
    ranges = REF_RANGES if from_reference else SHAPE_RANGES
    defaults = REF_DEFAULTS if from_reference else SHAPE_DEFAULTS
    spec = ranges[key]
    try:
        value = float(params.get(key, defaults[key]))
    except (TypeError, ValueError):
        value = float(defaults[key])
    return min(max(value, spec["lo"]), spec["hi"])


def cover_params(params: dict[str, Any]) -> CoverParams:
    """The shared parameter object, with the drawn-leg fields left at default."""
    fields = {k: v for k, v in params.items() if k in BASE_RANGES or k in ("operation", "hole_shape", "mask_mode", "relief_profile", "finish", "material", "colour_a", "colour_b", "motif_id", "motif_invert", "motif_align_flow", "split_halves")}
    for key in HIDDEN:
        fields.pop(key, None)
    return CoverParams.from_dict(fields)


@lru_cache(maxsize=24)
def _skin(
    clearance: float, fullness: float, top_z: float, bottom_clearance: float,
    wall: float, rows: int, from_reference: bool = False, deepen: float = 0.0,
    flexion_max: float = anat.FLEXION_MAX,
) -> tuple[AnatomicSurface, dict]:
    """The measured skin, cached: a slider move then costs a scale and a loft
    rather than another pass over the scan."""
    extra: dict = {}
    if not from_reference:
        # The rim is solved, not set: build the skin untrimmed, ask the flexion
        # test how high each column may stand, and cut there. That is what puts
        # the cover over the knee at the front and takes it away at the back.
        base = stage4_surface.build(
            clearance=clearance, fullness=fullness, wall=wall,
            top_z=anat.COVER_TOP_LIMIT, bottom_clearance=bottom_clearance, rows=8,
        )
        heights, radii = _thigh()
        extra["rim"] = stage5_flexion.smooth_rim(
            stage5_flexion.maximal_rim(
                base["zs"], base["centre"], base["radius"], heights, radii, top_z,
                wall, flexion_max,
            )
        )
    if from_reference:
        # The rim and the silhouette come off the renders; only where the
        # cover sits on the leg is left to decide, and that is `top_z`.
        probe = stage4_surface.build(top_z=top_z, bottom_clearance=bottom_clearance, rows=8)
        span = probe["report"]["top_z"] - probe["report"]["bottom_z"]
        t = np.linspace(0.0, 1.0, 512)
        extra = {
            "rim": anat_ref.rim_heights(stage4_surface.ANGLES, top_z, span, deepen),
            "girth": np.interp(
                anat.ANATOMY_T_BOTTOM
                + (1.0 - anat.ANATOMY_T_BOTTOM)
                * (probe["zs"] - probe["report"]["bottom_z"]) / span,
                t,
                anat_ref.girth(t),
            ),
        }
    built = stage4_surface.build(
        clearance=clearance,
        wall=wall,
        fullness=fullness,
        top_z=top_z,
        bottom_clearance=bottom_clearance,
        rows=rows,
        **extra,
    )
    skin = AnatomicSurface(
        built["zs"], built["centre"], built["radius"], built["rim"], stage4_surface.ANGLES
    )
    return skin, built


def build(params: dict[str, Any], draft: bool = False, from_reference: bool = False) -> dict[str, Any]:
    started = time.time()
    p = cover_params(params)
    wall = p.wall_thickness
    clearance = _clamp(params, "clearance", from_reference)
    # The wall eats into the clearance, so a wall thicker than the gap would
    # put the cover inside the prosthesis. Rather than refuse, the gap opens.
    opened = max(clearance, wall + 1.0)

    if from_reference:
        skin, measured = _skin(
            opened, _clamp(params, "fullness", True), _clamp(params, "seat_z", True),
            _clamp(params, "bottom_clearance", True), round(wall, 3),
            DRAFT_ROWS if draft else FINAL_ROWS,
            True, _clamp(params, "notch_deepen", True),
            _clamp(params, "flexion", True),
        )
    else:
        skin, measured = _skin(
            opened, _clamp(params, "fullness"), _clamp(params, "knee_cover"),
            _clamp(params, "bottom_clearance"), round(wall, 3),
            DRAFT_ROWS if draft else FINAL_ROWS,
            False, 0.0, _clamp(params, "flexion"),
        )

    leaves = None
    if bool(params.get("back_leaves", False)):
        def leaves(surface, cells, strut):
            if cells is None:
                return [], []
            return lv.place(
                surface,
                lv.LeafSpec(
                    count=int(round(_clamp(params, "leaf_count", from_reference))),
                    length=_clamp(params, "leaf_size", from_reference),
                    tilt=_clamp(params, "leaf_tilt", from_reference),
                    strut=strut,
                    a_max=cells.a_max,
                    profile=DEFAULT_PROFILE,
                ),
            )

    cover = generate(
        p,
        quality=DRAFT if draft else FINAL,
        profile=DEFAULT_PROFILE,
        surface=skin,
        extra_holes=leaves,
    )
    if opened > clearance + 1e-6:
        cover.notes.append(
            f"Clearance opened to {opened:.1f} mm so the {wall:.1f} mm wall still fits"
        )
    return {
        "cover": cover,
        "skin": skin,
        "measured": measured,
        "clearance": opened,
        "wall": wall,
        "seconds": time.time() - started,
        "flexion_target": _clamp(params, "flexion", from_reference),
    }


@lru_cache(maxsize=1)
def _prosthesis() -> trimesh.Trimesh:
    return trimesh.load(anat.WORK / "stage2_prosthesis.stl", process=False)


@lru_cache(maxsize=1)
def _thigh() -> tuple:
    return stage5_flexion.thigh_body(_prosthesis())


def flexion(mesh: trimesh.Trimesh, target: float = anat.FLEXION_MAX) -> dict[str, Any]:
    """How far the knee still bends before the cover meets the thigh."""
    heights, radii = _thigh()
    sweep = stage5_flexion.sweep(mesh, heights, radii, target)
    first_hit = next((r["angle"] for r in sweep if r["collision"]), None)
    reached = target if first_hit is None else first_hit - anat.FLEXION_STEP
    return {
        "max_angle": float(max(reached, 0.0)),
        "target": target,
        "clears": first_hit is None,
        "checked": len(sweep),
    }


def min_gap(built: dict[str, Any]) -> float:
    """Smallest gap left between the prosthesis and the inside of the wall."""
    prosthesis = np.asarray(_prosthesis().vertices)
    measured = built["measured"]
    zs, centre, radius = measured["zs"], measured["centre"], measured["radius"]
    angles = np.append(stage4_surface.ANGLES, stage4_surface.ANGLES[0] + 2 * np.pi)
    worst = float("inf")
    for i, z in enumerate(zs):
        # Below the knee only: higher up the scan is the socket, which the
        # cover is meant to miss rather than contain.
        if z > 0.0:
            continue
        band = prosthesis[np.abs(prosthesis[:, 2] - z) <= anat.COVER_SECTION_STEP]
        if len(band) < 10:
            continue
        offset = band[:, :2] - centre[i]
        # Read the cover in the bins it was built in; reading between them
        # under-reports the gap by a millimetre and a half.
        bins = np.clip(
            ((np.arctan2(offset[:, 1], offset[:, 0]) + np.pi) / (2 * np.pi) * anat.CONTOUR_BINS).astype(int),
            0, anat.CONTOUR_BINS - 1,
        )
        wall = radius[i][bins] - built["wall"]
        worst = min(worst, float((wall - np.linalg.norm(offset, axis=1)).min()))
    return worst if np.isfinite(worst) else 0.0


def stats(built: dict[str, Any], seconds: float, draft: bool) -> dict[str, Any]:
    """Everything the panel shows, plus the two numbers only this cover has."""
    cover: Cover = built["cover"]
    p = cover.params
    m = p.material_spec
    check = flexion(cover.mesh, built["flexion_target"])
    gap = min_gap(built)

    notes = list(cover.notes)
    if not check["clears"]:
        notes.insert(
            0,
            f"The knee jams at {check['max_angle']:.0f}\u00b0. Deepen the back notch "
            f"until it reaches {check['target']:.0f}\u00b0.",
        )
    if gap < 0.5:
        notes.insert(0, f"Only {gap:.1f} mm left over the prosthesis. Open the clearance.")
    if anat.RIM_PROVISIONAL:
        notes.append("Rim shape is provisional: ref_1.png and ref_2.png are not in data/.")

    return {
        "mass_g": round(cover.mass_g, 1),
        "plain_mass_g": round(cover.plain_mass_g, 1),
        "saving_pct": round(cover.saving_pct),
        "delta_g": round(cover.mass_g - cover.plain_mass_g, 1),
        "holes": cover.holes,
        "triangles": len(cover.mesh.faces),
        "max_wall_thickness": round(cover.max_wall, 2),
        "max_relief_depth": round(cover.max_relief, 2),
        "operation": p.operation,
        "cuts_through": cover.cuts_through,
        "notes": notes,
        "material": {"key": m.key, "label": m.label, "hex": m.hex, "polymer": m.polymer},
        "finish": {
            "mode": p.finish,
            "colour_a": m.hex,
            "colour_b": p.colour_b_spec.hex,
            "facet_scale": p.facet_scale,
        },
        "draft": draft,
        "seconds": round(seconds, 2),
        "watertight": bool(cover.mesh.is_watertight),
        "flexion": check,
        "min_gap_mm": round(gap, 2),
        "clearance_mm": round(built["clearance"], 1),
    }
