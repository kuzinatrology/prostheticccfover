"""Stage 1 — turn the raw scan into a clean, upright, labelled prosthesis.

The file the brief calls a scan of a prosthesis is a photogrammetry scan of a
seated person: two legs, both arms, a crutch, the seat and a good deal of
scanner debris, all in one arbitrary frame.  So the work here is as much
finding the prosthesis as cleaning it.

    .venv/bin/python -m anatomic.stage1_prepare

Writes work/stage1_prosthesis.stl, work/stage1.json and renders/stage1_*.png.
Re-runnable on its own; nothing here writes to the original scan.
"""

from __future__ import annotations

import json
import shutil
import time

import fast_simplification
import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from . import config, render


# ------------------------------------------------------------------ mesh ---


def weld(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Merge vertices that sit on top of each other, so the mesh has a
    connectivity graph at all.  An STL is a bag of triangles until this runs."""
    key = np.round(vertices / config.WELD_TOL_MM).astype(np.int64)
    unique, inverse = np.unique(key, axis=0, return_inverse=True)
    merged = np.zeros((len(unique), 3))
    merged[inverse] = vertices
    return merged, inverse[faces]


def components(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Label each face with the connected piece of surface it belongs to."""
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    graph = coo_matrix(
        (np.ones(len(edges)), (edges[:, 0], edges[:, 1])),
        shape=(len(vertices),) * 2,
    )
    _, label = connected_components(graph, directed=False)
    return label[faces[:, 0]]


def compact(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop vertices no face refers to and renumber."""
    used, remapped = np.unique(faces, return_inverse=True)
    return vertices[used], remapped.reshape(-1, 3)


def signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    """Divergence-theorem volume.  Meaningless in absolute terms on an open
    mesh, but its sign still says which way the winding runs."""
    a, b, c = (vertices[faces[:, i]] for i in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


# ------------------------------------------------------------------ limb ---


def isolate_limb(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cut a cylinder around the seed axis, then keep its largest piece.

    The cylinder catches the limb plus whatever the shorts and the seat put
    nearby; those come away as separate surfaces, so one connected-component
    pass finishes the job.
    """
    top = np.array(config.LIMB_SEED_TOP)
    bottom = np.array(config.LIMB_SEED_BOTTOM)
    axis = bottom - top
    length = np.linalg.norm(axis)
    axis = axis / length

    along = (vertices - top) @ axis
    across = np.linalg.norm((vertices - top) - np.outer(along, axis), axis=1)
    inside = (
        (along > -config.LIMB_OVERSHOOT_TOP)
        & (along < length + config.LIMB_OVERSHOOT_BOTTOM)
        & (across < config.LIMB_RADIUS)
    )

    cropped = faces[inside[faces].all(axis=1)]
    v, f = compact(vertices, cropped)
    label = components(v, f)
    return compact(v, f[label == np.bincount(label).argmax()])


def perpendiculars(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Any two directions across `axis`.  Picking the seed off whichever world
    axis is least aligned keeps the cross product well conditioned when the
    limb is already upright."""
    seed = np.eye(3)[int(np.argmin(np.abs(axis)))]
    x = np.cross(seed, axis)
    x /= np.linalg.norm(x)
    return x, np.cross(axis, x)


def section_widths(vertices: np.ndarray, axis: np.ndarray, origin: np.ndarray, step: float):
    """Width of the limb across two perpendicular directions, every `step` up
    the axis.  The pylon shows up as a long flat stretch in both."""
    frame_x, frame_y = perpendiculars(axis)
    local = (vertices - origin) @ np.stack([frame_x, frame_y, axis]).T

    edges = np.arange(np.floor(local[:, 2].min()), local[:, 2].max(), step)
    heights, wx, wy = [], [], []
    for lo in edges:
        band = local[(local[:, 2] >= lo) & (local[:, 2] < lo + step)]
        if len(band) < 20:
            continue
        heights.append(lo + step / 2)
        wx.append(np.ptp(band[:, 0]))
        wy.append(np.ptp(band[:, 1]))
    return np.array(heights), np.array(wx), np.array(wy)


def smooth(values: np.ndarray, window: int = 3) -> np.ndarray:
    """Median filter over neighbouring sections.  Single noisy sections
    otherwise break an otherwise constant stretch in two."""
    pad = window // 2
    padded = np.pad(values, pad, mode="edge")
    return np.array([np.median(padded[i : i + window]) for i in range(len(values))])


def find_pylon(heights, wx, wy) -> tuple[float, float]:
    """The longest run of sections that are round and the catalogue diameter.

    This is the one part of the prosthesis whose true size is known, so it
    fixes the units and gives a straight reference for the axis.
    """
    wx, wy = smooth(wx), smooth(wy)
    width = np.maximum(wx, wy)
    ok = (
        (np.abs(width - config.PYLON_DIAMETER) < config.PYLON_DIAMETER_TOL)
        & (np.abs(wx - wy) < config.PYLON_ROUNDNESS_TOL)
    )
    best = run = None
    for i, good in enumerate(ok):
        if good:
            run = i if run is None else run
        elif run is not None:
            if best is None or i - run > best[1] - best[0]:
                best = (run, i)
            run = None
    if run is not None and (best is None or len(ok) - run > best[1] - best[0]):
        best = (run, len(ok))
    if best is None:
        raise SystemExit("no pylon-like stretch found — check LIMB_SEED_* and the units")
    lo, hi = heights[best[0]], heights[best[1] - 1]
    if hi - lo < config.PYLON_MIN_LENGTH:
        raise SystemExit(f"pylon candidate only {hi - lo:.0f} mm long — too short to trust")
    return float(lo), float(hi)


def refine_axis(vertices, axis, origin, pylon_range) -> np.ndarray:
    """Re-fit the axis to the pylon alone.  The seed axis runs socket-to-foot
    through a bent leg; the pylon is genuinely straight, so it is the better
    ruler for 'up'."""
    along = (vertices - origin) @ axis
    band = vertices[(along >= pylon_range[0]) & (along <= pylon_range[1])]
    centred = band - band.mean(axis=0)
    direction = np.linalg.svd(centred, full_matrices=False)[2][0]
    return direction * np.sign(direction @ axis)


def forward_direction(local: np.ndarray, foot_top: float) -> np.ndarray:
    """Which way the toes point, from the shape of the foot.

    The foot is much longer toward the toes than toward the heel, so the
    principal direction of the foot's footprint, signed by which end reaches
    further, is the front of the leg.
    """
    foot = local[local[:, 2] < foot_top][:, :2]
    foot = foot - np.median(foot, axis=0)
    direction = np.linalg.svd(foot - foot.mean(0), full_matrices=False)[2][0]
    projected = foot @ direction
    if abs(projected.max()) < abs(projected.min()):
        direction = -direction
    return np.array([direction[0], direction[1], 0.0])


def label_parts(local: np.ndarray, faces: np.ndarray, pylon: tuple[float, float]) -> dict:
    """Split the limb into socket / knee / pylon / foot adapter / foot by the
    height at which the cross-section crosses each width threshold."""
    heights, wx, wy = section_widths(local, np.array([0.0, 0.0, 1.0]), np.zeros(3), config.SECTION_STEP)
    width = smooth(np.maximum(wx, wy))

    # Upwards: the knee module swells well past the pylon, then the surface
    # pinches at the hem of the shorts before the thigh flares out again.  That
    # pinch, not a width threshold, is where the knee ends and the socket
    # begins, so look for the narrowest section between the two crossings.
    above = np.flatnonzero(heights > pylon[1])
    knee_top = float(heights[above[-1]]) if len(above) else pylon[1]
    if len(above):
        grown = above[width[above] > config.KNEE_MIN_WIDTH]
        if len(grown):
            flared = above[(above > grown[0]) & (width[above] > config.SOCKET_MIN_WIDTH)]
            end = flared[0] if len(flared) else above[-1]
            span = np.arange(grown[0], max(end, grown[0] + 1))
            knee_top = float(heights[span[np.argmin(width[span])]])

    # Downwards: the shoe is the first thing wider than a foot adapter can be.
    below = np.flatnonzero(heights < pylon[0])[::-1]
    foot_top = float(heights[below[0]]) if len(below) else pylon[0]
    wide = below[width[below] > config.FOOT_MIN_WIDTH]
    if len(wide):
        foot_top = float(heights[wide[0]])

    return {
        "pylon": (pylon[0], pylon[1]),
        "knee": (pylon[1], knee_top),
        "socket": (knee_top, float(local[:, 2].max())),
        "foot_adapter": (foot_top, pylon[0]),
        "foot": (float(local[:, 2].min()), foot_top),
    }


# ------------------------------------------------------------------ main ---


def main() -> None:
    started = time.time()
    config.WORK.mkdir(parents=True, exist_ok=True)
    config.DATA.mkdir(parents=True, exist_ok=True)

    if not config.SCAN_COPY.exists():
        shutil.copy2(config.SCAN_SOURCE, config.SCAN_COPY)
    raw = trimesh.load(config.SCAN_COPY, process=False)

    vertices, faces = weld(np.asarray(raw.vertices), np.asarray(raw.faces))
    label = components(vertices, faces)
    sizes = np.bincount(label)
    scene = {
        "faces_in": int(len(raw.faces)),
        "vertices_welded": int(len(vertices)),
        "components": int(len(sizes)),
        "component_faces": sorted(map(int, sizes), reverse=True),
        "junk_components_dropped": int((sizes < config.JUNK_FACE_COUNT).sum()),
        "signed_volume_raw": signed_volume(vertices, faces),
    }
    faces = faces[np.isin(label, np.flatnonzero(sizes >= config.JUNK_FACE_COUNT))]

    limb_v, limb_f = isolate_limb(vertices, faces)

    seed_axis = np.array(config.LIMB_SEED_BOTTOM) - np.array(config.LIMB_SEED_TOP)
    seed_axis /= np.linalg.norm(seed_axis)
    seed_up = -seed_axis
    origin = np.array(config.LIMB_SEED_TOP)

    heights, wx, wy = section_widths(limb_v, seed_up, origin, config.SECTION_STEP)
    pylon = find_pylon(heights, wx, wy)
    up = refine_axis(limb_v, seed_up, origin, pylon)

    # Rebuild the profile on the refined axis, then lock the frame to it.
    heights, wx, wy = section_widths(limb_v, up, origin, config.SECTION_STEP)
    pylon = find_pylon(heights, wx, wy)

    frame_x, frame_y = perpendiculars(up)
    local = (limb_v - origin) @ np.stack([frame_x, frame_y, up]).T
    local[:, 2] -= pylon[1]                       # z = 0 at the top of the pylon
    pylon = (pylon[0] - pylon[1], 0.0)

    foot_guess = pylon[0] - 80.0
    forward = forward_direction(local, foot_guess)
    forward /= np.linalg.norm(forward)
    # +y forward, z up, x = y x z so the frame stays right-handed.
    rotate = np.stack([np.cross(forward, [0, 0, 1.0]), forward, [0, 0, 1.0]])
    local = local @ rotate.T

    if signed_volume(local, limb_f) < 0:
        limb_f = limb_f[:, ::-1]
        flipped = True
    else:
        flipped = False

    reduction = max(0.0, 1.0 - config.TARGET_FACES / len(limb_f))
    if reduction > 0:
        sv, sf = fast_simplification.simplify(
            local.astype(np.float32), limb_f.astype(np.int32), reduction
        )
        local, limb_f = np.asarray(sv, float), np.asarray(sf, int)

    parts = label_parts(local, limb_f, pylon)
    mesh = trimesh.Trimesh(local, limb_f, process=False)
    mesh.export(config.WORK / "stage1_prosthesis.stl")

    heights, wx, wy = section_widths(local, np.array([0.0, 0.0, 1.0]), np.zeros(3), config.SECTION_STEP)
    report = {
        "scene": scene,
        "limb_faces_isolated": int(len(limb_f)),
        "units": "mm",
        "units_evidence": {
            "pylon_width_x_mm": float(np.median(wx[(heights > pylon[0]) & (heights < pylon[1])])),
            "pylon_width_y_mm": float(np.median(wy[(heights > pylon[0]) & (heights < pylon[1])])),
            "catalogue_pylon_diameter_mm": config.PYLON_DIAMETER,
        },
        "frame": {
            "up_in_scan_coords": up.tolist(),
            "forward_in_scan_coords": (forward @ np.stack([frame_x, frame_y, up])).tolist(),
            "origin_in_scan_coords": origin.tolist(),
            "z_zero_at": "top of the pylon",
        },
        "normals_flipped": flipped,
        "limb_length_mm": float(np.ptp(local[:, 2])),
        "parts_z_mm": {k: [round(a, 1), round(b, 1)] for k, (a, b) in parts.items()},
        "profile": [
            {"z": round(float(z), 1), "width_x": round(float(a), 1), "width_y": round(float(b), 1)}
            for z, a, b in zip(heights, wx, wy)
        ],
        "seconds": round(time.time() - started, 1),
    }
    (config.WORK / "stage1.json").write_text(json.dumps(report, indent=2))

    draw_parts(local, limb_f, parts)
    print(json.dumps({k: v for k, v in report.items() if k != "profile"}, indent=2))


def draw_parts(vertices: np.ndarray, faces: np.ndarray, parts: dict) -> None:
    """Front, side and three-quarter renders with the parts coloured and named."""
    centre = vertices[faces].mean(axis=1)[:, 2]
    colour = np.tile(np.array(config.PART_COLOURS["unassigned"], float), (len(faces), 1))
    labels = []
    for name, (lo, hi) in parts.items():
        band = (centre >= lo) & (centre < hi)
        colour[band] = config.PART_COLOURS[name]
        if band.any():
            labels.append((
                [0.0, 0.0, (lo + hi) / 2],
                f"{name}  {hi - lo:.0f} mm",
                (40, 40, 40),
            ))

    bounds = (vertices.min(0), vertices.max(0))
    paths = []
    for view in ("front", "side", "three_quarter"):
        path = config.RENDERS / f"stage1_{view}.png"
        render.render(
            [(vertices, faces, colour)],
            view,
            path,
            bounds=bounds,
            labels=labels if view != "front" else None,
            title=f"stage 1 — {view.replace('_', ' ')}",
        )
        paths.append(path)
    render.contact_sheet(paths, config.RENDERS / "stage1_sheet.png", columns=3)


if __name__ == "__main__":
    main()
