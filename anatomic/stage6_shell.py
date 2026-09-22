"""Stage 6 — give the surface a wall and close it.

The surface from stage 4 (with the notch stage 5 settled on) is offset inward
along its own normals by the wall thickness and the two skins are joined round
the rim and round the bottom opening.  The result is one closed manifold: a
tube with a wall, which is what a cover is.

    .venv/bin/python -m anatomic.stage6_shell
"""

from __future__ import annotations

import json

import numpy as np
import trimesh

from . import config, render, stage4_surface, stage5_flexion


def open_loft(grid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The lofted surface without the bottom cap."""
    rows, cols, _ = grid.shape
    index = np.arange(rows * cols).reshape(rows, cols)
    right = (np.arange(cols) + 1) % cols
    a, b = index[:-1, :], index[:-1, right]
    c, d = index[1:, right], index[1:, :]
    faces = np.concatenate([
        np.stack([a, b, c], -1).reshape(-1, 3),
        np.stack([a, c, d], -1).reshape(-1, 3),
    ])
    return grid.reshape(-1, 3), faces


def shell(grid: np.ndarray, thickness: float) -> trimesh.Trimesh:
    """Outer skin, inner skin, and a band closing each opening."""
    rows, cols, _ = grid.shape
    outer, faces = open_loft(grid)
    # Offset straight in along the section's own radius, not along the surface
    # normal. A normal near the rim leans along the cut, so following it slides
    # the inner vertex sideways into a neighbouring column — one whose rim may
    # sit a centimetre lower — and puts material where the flexion test had
    # taken it away. Radially, the inner skin keeps both its angle and its
    # height, and the leg tapers gently enough that the wall loses under two
    # per cent of its thickness by it.
    from .stage4_surface import ANGLES

    direction = np.stack([np.cos(ANGLES), np.sin(ANGLES), np.zeros(cols)], axis=-1)
    inner = outer - np.tile(direction, (rows, 1)) * thickness

    vertices = np.vstack([outer, inner])
    offset = len(outer)
    index = np.arange(rows * cols).reshape(rows, cols)
    right = (np.arange(cols) + 1) % cols

    def band(ring_a: np.ndarray, ring_b: np.ndarray) -> np.ndarray:
        return np.concatenate([
            np.stack([ring_a, ring_a[right], ring_b[right]], -1),
            np.stack([ring_a, ring_b[right], ring_b], -1),
        ])

    all_faces = np.vstack([
        faces,
        faces[:, ::-1] + offset,
        band(index[-1], index[-1] + offset),          # the rim
        band(index[0] + offset, index[0]),            # the bottom opening
    ])

    mesh = trimesh.Trimesh(vertices, all_faces, process=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def main() -> None:
    rim = np.load(config.WORK / "stage5_rim.npy")
    built = stage4_surface.build(top_z=config.COVER_TOP_Z, rim=rim)

    mesh = shell(built["grid"], config.WALL_THICKNESS_MM)
    mesh.export(config.OUTPUT_STL)

    volume_cm3 = float(mesh.volume) / 1000.0
    report = {
        "output": str(config.OUTPUT_STL),
        "wall_thickness_mm": config.WALL_THICKNESS_MM,
        "clearance_mm": config.CLEARANCE_MM,
        "rim_highest_mm": round(float(rim.max()), 1),
        "rim_lowest_mm": round(float(rim.min()), 1),
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "euler_number": int(mesh.euler_number),
        "volume_cm3": round(volume_cm3, 1),
        "mass_g": round(volume_cm3 * config.MATERIAL_DENSITY_G_CM3, 1),
        "height_mm": round(float(np.ptp(mesh.vertices[:, 2])), 1),
        "bounds_mm": np.asarray(mesh.bounds).round(1).tolist(),
    }

    try:
        from manifold3d import Manifold, Mesh
        solid = Manifold(Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        ))
        report["manifold3d_volume_cm3"] = round(solid.volume() / 1000.0, 1)
        report["manifold3d_ok"] = solid.num_tri() > 0
    except Exception as exc:  # pragma: no cover - reported, not raised
        report["manifold3d_ok"] = False
        report["manifold3d_error"] = str(exc)

    report["checks"] = verify(mesh, built)
    (config.WORK / "stage6.json").write_text(json.dumps(report, indent=2))
    draw(mesh, built)
    print(json.dumps(report, indent=2))


def verify(mesh: trimesh.Trimesh, built: dict) -> dict:
    """The two claims worth checking on the finished solid rather than on the
    surface it was built from: the prosthesis still fits inside it, and it
    still bends."""
    prosthesis = np.asarray(
        trimesh.load(config.WORK / "stage2_prosthesis.stl", process=False).vertices
    )
    # Smallest gap between the prosthesis and the inside of the wall, measured
    # section by section along the cover.
    zs, centre, radius = built["zs"], built["centre"], built["radius"]
    gaps = []
    for i, z in enumerate(zs):
        # Only below the knee axis: above it the scan is the socket, which the
        # cover is meant to miss rather than to contain, and how near it runs
        # is the flexion test's business, not this one's.
        if z > 0.0:
            continue
        band = prosthesis[np.abs(prosthesis[:, 2] - z) <= config.COVER_SECTION_STEP]
        if len(band) < 10:
            continue
        offset = band[:, :2] - centre[i]
        # Read the cover in the same angular bins it was built in: reading it
        # between them interpolates across a 2 degree step and under-reports
        # the gap by a millimetre and a half.
        angle = np.arctan2(offset[:, 1], offset[:, 0])
        bins = np.clip(
            ((angle + np.pi) / (2 * np.pi) * config.CONTOUR_BINS).astype(int),
            0, config.CONTOUR_BINS - 1,
        )
        wall = radius[i][bins] - config.WALL_THICKNESS_MM
        gaps.append(float((wall - np.linalg.norm(offset, axis=1)).min()))

    heights, radii = stage5_flexion.thigh_body(
        trimesh.load(config.WORK / "stage2_prosthesis.stl", process=False)
    )
    sweep = stage5_flexion.sweep(mesh, heights, radii)

    return {
        "min_gap_to_prosthesis_mm": round(min(gaps), 2),
        "gap_target_mm": config.CLEARANCE_MM,
        "sections_checked": len(gaps),
        "flexion_collisions": sum(r["collision"] for r in sweep),
        "flexion_steps": len(sweep),
    }


def draw(mesh: trimesh.Trimesh, built: dict) -> None:
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    colour = config.PART_COLOURS["socket"]
    paths = []
    for name, view in (
        ("front", "front"), ("side", "side"),
        ("three_quarter", "three_quarter"), ("reference", config.REFERENCE_VIEW),
    ):
        path = config.RENDERS / f"stage6_{name}.png"
        render.render([(v, f, colour)], view, path, title=f"stage 6 — {name.replace('_', ' ')}")
        paths.append(path)
    render.contact_sheet(paths, config.RENDERS / "stage6_sheet.png", columns=4)

    # The rim, close up, and a cut-away so the 3 mm wall is visible.
    rim_v, rim_f = stage4_surface.loft(built["grid"][int(config.COVER_ROWS * 0.8):])
    render.render([(rim_v, rim_f, colour)], (0.55, 0.72, -0.42),
                  config.RENDERS / "stage6_rim.png", height=950,
                  title="stage 6 — rim close up")

    half = f[(v[f][:, :, 0] > v[:, 0].mean()).any(axis=1)]
    render.render([(v, half, colour)], "side", config.RENDERS / "stage6_wall.png",
                  height=950, title="stage 6 — half cut away, 3 mm wall")


if __name__ == "__main__":
    main()
