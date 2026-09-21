"""Renders and numbers for the stage reports of the transfemoral cover.

    python -m tools.stage_renders            # every stage, final quality
    python -m tools.stage_renders --draft

Writes renders/stage_N_{side,front,back}.png and renders/stages.json.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import mesh_build as mb
from backend.transfemoral import config as cfg
from backend.transfemoral.generator import DRAFT, FINAL, generate
from backend.transfemoral.params import TFParams
from tools.render import render_views

FRONT = (150, 172, 184)
BACK = (112, 138, 152)
CLAMP = (190, 150, 110)
OUT = ROOT / "renders"


def _cut(mesh: trimesh.Trimesh, keep_positive_x: bool, x: float) -> trimesh.Trimesh:
    """Half a body, sliced by a sagittal plane, to show its wall."""
    sign = 1.0 if keep_positive_x else -1.0
    man = mb.to_manifold(mesh).trim_by_plane([sign, 0.0, 0.0], sign * x)
    return mb.from_manifold(man)


def _offset(mesh: trimesh.Trimesh, dy: float) -> trimesh.Trimesh:
    out = mesh.copy()
    out.apply_translation([0.0, dy, 0.0])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true")
    args = ap.parse_args(argv)
    q = DRAFT if args.draft else FINAL
    numbers: dict = {}

    # 2. the notch: a plain shell, both halves in one colour.
    plain = generate(TFParams(operation="none"), quality=q)
    parts = [(plain.bodies["front"], FRONT), (plain.bodies["back"], FRONT)]
    render_views(parts, OUT / "stage_2")
    lay = plain.layout
    numbers["notch"] = {
        "knee_axis": [round(lay.knee.axis_y, 1), lay.knee.axis_z],
        "flexion_angle": lay.knee.flexion,
        "notch_split": lay.knee.split,
        "sector_edges_deg": [round(np.degrees(lay.knee.lower), 1), round(np.degrees(lay.knee.upper), 1)],
        "fillet": lay.knee.fillet,
        "thigh_radius": round(lay.thigh.radius, 1),
        "thigh_clearance": lay.thigh.clearance,
        "seam_meets_notch_z": {str(k): round(s.meet, 1) for k, s in lay.sides.items()},
    }

    # 3. the wall: the same shell cut down the middle, seen from the side.
    cx = float(lay.surface.centre(0.0)[0])
    cut = [(_cut(plain.bodies["front"], True, cx), FRONT), (_cut(plain.bodies["back"], True, cx), BACK)]
    render_views(cut, OUT / "stage_3", views=("side",))
    render_views([(plain.bodies["front"], FRONT)], OUT / "stage_3", views=("front", "back"))
    numbers["wall"] = {
        "wall": plain.wall,
        "max_wall": round(plain.max_wall, 2),
        "volumes_mm3": {k: round(v) for k, v in plain.volumes.items()},
    }

    # 4. halves, seam and the pattern fading at every edge.
    cover = generate(TFParams(), quality=q)
    parts = [(cover.bodies["front"], FRONT), (cover.bodies["back"], BACK)]
    render_views(parts, OUT / "stage_4")
    numbers["halves"] = {
        "holes": cover.holes,
        "front_holes": len(cover.rings["front"]),
        "back_holes": len(cover.rings["back"]),
        "seam_offset_limit": round(cover.limits["seam_offset"][1], 1),
        "back_half_min_span_deg": round(cover.layout.back_span_deg, 1),
        "seam_solid_floor": round(cover.limits["seam_solid_width"][0], 2),
        "notes": cover.notes,
    }

    # 5. magnets: the front half from behind, with its shelves and sockets.
    render_views([(cover.bodies["front"], FRONT)], OUT / "stage_5", views=("back",))
    render_views([(cover.bodies["back"], BACK)], OUT / "stage_5", views=("front", "side"))
    spec = cover.spec
    numbers["magnets"] = {
        "shelf_width": round(spec.width, 2),
        "pad_thickness": round(spec.pad, 2),
        "shelf_top_depth": round(spec.shelf_top, 2),
        "shelf_bottom_depth": round(spec.shelf_bottom, 2),
        "socket": [round(2 * spec.socket_radius, 2), round(spec.socket_depth, 2)],
        "sites_z": {str(k): [round(float(m.point[2]), 1) for m in v] for k, v in cover.magnets.items()},
    }

    # 6. clamps, in place and on their own.
    clamps = [(cover.bodies[k], CLAMP) for k in ("lower_clamp_back", "upper_clamp_back") if k in cover.bodies]
    render_views([(cover.bodies["front"], FRONT)] + clamps, OUT / "stage_6", views=("back", "side"))
    numbers["clamps"] = {
        name: {
            "z": plan.z,
            "range": [plan.lo, plan.hi],
            "ring": round(plan.ring, 2),
            "ribs": len(plan.ribs),
            "rib_width": round(plan.rib_width, 2),
            "height": plan.shape.height,
            "bolt_x": round(plan.shape.bolt_x, 2),
        }
        for name, plan in cover.plans.items()
    }
    numbers["pylon_tilt_deg"] = round(cover.pylon.tilt_deg, 1)
    numbers["module_bottom_z"] = round(cover.pylon.module_bottom_z, 1)

    # 7. out: exploded, with masses.
    apart = [(cover.bodies["front"], FRONT), (_offset(cover.bodies["back"], -cfg.EXPLODE_MM), BACK)]
    apart += [(_offset(m, -cfg.EXPLODE_MM), c) for m, c in clamps]
    render_views(apart, OUT / "stage_7")
    numbers["output"] = {
        "masses_g": {k: round(v, 1) for k, v in cover.masses.items()},
        "total_g": round(cover.mass_g, 1),
        "plain_g": round(cover.plain_mass_g, 1),
        "triangles": {k: len(m.faces) for k, m in cover.bodies.items()},
    }

    (OUT / "stages.json").write_text(json.dumps(numbers, indent=2, ensure_ascii=False))
    print(json.dumps(numbers, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
