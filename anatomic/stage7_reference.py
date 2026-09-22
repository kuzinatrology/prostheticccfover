"""Stage 7 — the cover the reference renders describe.

Stages 4 to 6 build a cover whose silhouette is a human shank and whose rim I
placed by eye.  This one takes both from the renders instead:

* the rim is traced off ref_2, which is a straight side view, so the top
  boundary of its silhouette is the rim curve itself;
* the girth profile is the mean of both silhouettes.

The prosthesis still sets the size, and the knee still has to bend, so the one
thing the renders cannot supply is where the cover sits on the leg.  That is
searched for: the reference notch is narrow, and a narrow notch will not clear
the thigh at deep flexion however deep it is cut, because by then the thigh is
beside the cover and not only behind it.  Lowering the whole cover fixes it
with the reference's own shape left alone.

    .venv/bin/python -m anatomic.stage7_reference
"""

from __future__ import annotations

import json

import numpy as np
import trimesh

from . import config, reference, render, stage4_surface, stage5_flexion, stage6_shell


def build(top_z: float, deepen: float = 0.0, rows: int | None = None) -> dict:
    built = stage4_surface.build(top_z=top_z, rows=rows)
    span = built["report"]["top_z"] - built["report"]["bottom_z"]
    rim = reference.rim_heights(stage4_surface.ANGLES, top_z, span, deepen)
    t = np.linspace(0.0, 1.0, 512)
    return stage4_surface.build(
        top_z=top_z,
        rows=rows,
        rim=rim,
        girth=np.interp(
            config.ANATOMY_T_BOTTOM
            + (1.0 - config.ANATOMY_T_BOTTOM)
            * (built["zs"] - built["report"]["bottom_z"]) / span,
            t,
            reference.girth(t),
        ),
    )


def seat(wall: float = config.WALL_THICKNESS_MM) -> tuple[float, list[dict]]:
    """Lowest seating height that still reaches full flexion, to the nearest
    2 mm, searched downward from the knee axis."""
    prosthesis = trimesh.load(config.WORK / "stage2_prosthesis.stl", process=False)
    heights, radii = stage5_flexion.thigh_body(prosthesis)
    tried = []
    for top_z in np.arange(0.0, -220.0, -2.0):
        built = build(float(top_z))
        sweep = stage5_flexion.sweep(stage6_shell.shell(built["grid"], wall), heights, radii)
        first = next((r["angle"] for r in sweep if r["collision"]), None)
        reached = config.FLEXION_MAX if first is None else first - config.FLEXION_STEP
        tried.append({"top_z": float(top_z), "reaches_deg": float(max(reached, 0.0))})
        if first is None:
            return float(top_z), tried
    raise SystemExit("the reference rim never clears the thigh, at any seating height")


def main() -> None:
    top_z = config.REFERENCE_TOP_Z
    built = build(top_z, config.REFERENCE_DEEPEN_MM)
    mesh = stage6_shell.shell(built["grid"], config.WALL_THICKNESS_MM)
    mesh.export(config.OUTPUT_REFERENCE_STL)

    prosthesis = trimesh.load(config.WORK / "stage2_prosthesis.stl", process=False)
    heights, radii = stage5_flexion.thigh_body(prosthesis)
    sweep = stage5_flexion.sweep(mesh, heights, radii)
    data = reference.read()

    volume_cm3 = float(mesh.volume) / 1000.0
    report = {
        "output": str(config.OUTPUT_REFERENCE_STL),
        "top_z": top_z,
        "bottom_z": built["report"]["bottom_z"],
        "rim_front_dip_pct": round(100 * data["rim_front_dip"], 1),
        "rim_back_dip_pct": round(100 * data["rim_back_dip"], 1),
        "rim_back_z": round(float(built["rim"].min()), 1),
        "rim_side_z": round(float(built["rim"].max()), 1),
        "widest_at_t": {k: round(v["widest_at_t"], 3) for k, v in data["girth"].items()},
        "watertight": bool(mesh.is_watertight),
        "faces": int(len(mesh.faces)),
        "volume_cm3": round(volume_cm3, 1),
        "mass_g": round(volume_cm3 * config.MATERIAL_DENSITY_G_CM3, 1),
        "height_mm": round(float(np.ptp(mesh.vertices[:, 2])), 1),
        "flexion_collisions": sum(r["collision"] for r in sweep),
        "flexion_steps": len(sweep),
    }
    (config.WORK / "stage7.json").write_text(json.dumps(report, indent=2))

    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    paths = []
    for name, view in (("front", "front"), ("side", "side"),
                       ("three_quarter", "three_quarter"), ("reference", config.REFERENCE_VIEW)):
        path = config.RENDERS / f"stage7_{name}.png"
        render.render([(v, f, config.PART_COLOURS["socket"])], view, path,
                      title=f"stage 7 — from the reference, {name.replace('_', ' ')}")
        paths.append(path)
    render.contact_sheet(paths, config.RENDERS / "stage7_sheet.png", columns=4)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
