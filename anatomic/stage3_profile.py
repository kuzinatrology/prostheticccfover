"""Stage 3 — where the shape comes from: MakeHuman for proportion, the
reference renders for style.

Only ratios are taken from the human leg: the shape of each cross-section and
how thick it is against how wide, at each relative height between ankle and
knee.  Absolute size is the prosthesis's business (stage 4).

    .venv/bin/python -m anatomic.stage3_profile

Writes work/stage3_shank.stl, work/stage3_profile.npz, work/stage3.json,
renders/stage3_*.png.
"""

from __future__ import annotations

import collections
import json
import urllib.request

import numpy as np
import trimesh

from . import config, render


# ------------------------------------------------------------- makehuman ---


def load_base_mesh() -> tuple[np.ndarray, dict[str, list[list[int]]]]:
    """Read the OBJ keeping its groups, which is the only way to tell the body
    apart from the eyes, teeth, skirt and joint cubes sharing the file."""
    if not config.MAKEHUMAN_OBJ.exists():
        config.MAKEHUMAN_OBJ.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(config.MAKEHUMAN_URL, config.MAKEHUMAN_OBJ)

    vertices: list[list[float]] = []
    groups: dict[str, list[list[int]]] = collections.defaultdict(list)
    current = None
    for line in config.MAKEHUMAN_OBJ.read_text().splitlines():
        if line.startswith("v "):
            vertices.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("g "):
            current = line.split(None, 1)[1].strip()
        elif line.startswith("f "):
            groups[current].append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
    return np.array(vertices), groups


def triangulate(quads: list[list[int]]) -> np.ndarray:
    faces = []
    for face in quads:
        for i in range(1, len(face) - 1):
            faces.append([face[0], face[i], face[i + 1]])
    return np.array(faces)


def joint_centre(vertices: np.ndarray, groups: dict, name: str) -> np.ndarray:
    """MakeHuman marks each joint with a little cube; its centre is the joint."""
    return vertices[np.unique(np.concatenate(groups[name]))].mean(axis=0)


# ----------------------------------------------------------------- shank ---


def shank_frame(knee: np.ndarray, ankle: np.ndarray, front: np.ndarray):
    """Local frame of the shank: z from ankle to knee, y toward the toes."""
    up = knee - ankle
    up /= np.linalg.norm(up)
    forward = front - up * (front @ up)
    forward /= np.linalg.norm(forward)
    return np.stack([np.cross(forward, up), forward, up])


def star_contour(points: np.ndarray, bins: int) -> np.ndarray | None:
    """Same envelope-per-angle idea as stage 2, on a closed clean mesh this
    time, so it is only smoothing away the odd crease."""
    if len(points) < 24:
        return None
    centre = points.mean(axis=0)
    offset = points - centre
    angle = np.arctan2(offset[:, 1], offset[:, 0])
    radius = np.linalg.norm(offset, axis=1)
    edges = np.linspace(-np.pi, np.pi, bins + 1)
    index = np.clip(np.digitize(angle, edges) - 1, 0, bins - 1)
    out = np.full(bins, -np.inf)
    np.maximum.at(out, index, radius)
    out[np.isneginf(out)] = np.nan
    known = np.flatnonzero(~np.isnan(out))
    if len(known) < bins // 4:
        return None
    centres = (edges[:-1] + edges[1:]) / 2
    if len(known) < bins:
        out = np.interp(
            centres,
            np.concatenate([centres[known] - 2 * np.pi, centres[known], centres[known] + 2 * np.pi]),
            np.tile(out[known], 3),
        )
    return np.stack([centre[0] + out * np.cos(centres), centre[1] + out * np.sin(centres)], -1)


def section_points(mesh, z: float, samples: int = 2000) -> np.ndarray | None:
    """A real plane cut through the shank, densified into a point cloud.

    Unlike the scan, this mesh is clean and closed, so intersecting triangles
    gives an exact outline instead of an envelope.  The outline is then
    resampled evenly so the angular binning below has something to bite on at
    every angle, however sparse the mesh is at that height.
    """
    try:
        path = mesh.section(plane_origin=[0.0, 0.0, z], plane_normal=[0.0, 0.0, 1.0])
    except Exception:
        return None
    if path is None or not len(path.entities):
        return None
    loops = [path.vertices[e.points] for e in path.entities]
    loop = max(loops, key=lambda p: np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
    step = np.linalg.norm(np.diff(loop, axis=0), axis=1)
    along = np.concatenate([[0.0], np.cumsum(step)])
    if along[-1] <= 0:
        return None
    even = np.linspace(0.0, along[-1], samples)
    return np.stack([np.interp(even, along, loop[:, i]) for i in range(2)], axis=-1)


# ------------------------------------------------------------- reference ---


def reference_silhouettes() -> dict:
    """Trace the outline of the cover in each reference render.

    The renders are a light object on a white ground, so background is whatever
    matches the corner pixel; the silhouette is the rest.  Returned as the half
    width at each relative height, which is what stage 4 compares against.
    """
    from PIL import Image

    out = {}
    for path in config.REF_IMAGES:
        if not path.exists():
            continue
        image = np.asarray(Image.open(path).convert("RGB"), dtype=int)
        corner = image[:8, :8].reshape(-1, 3).mean(axis=0)
        mask = np.abs(image - corner).max(axis=2) > config.REF_BACKGROUND_TOLERANCE
        rows = np.flatnonzero(mask.any(axis=1))
        if not len(rows):
            continue
        top, bottom = rows[0], rows[-1]
        height = bottom - top + 1
        left, right, centre = [], [], []
        for y in range(top, bottom + 1):
            xs = np.flatnonzero(mask[y])
            left.append(xs[0]); right.append(xs[-1]); centre.append((xs[0] + xs[-1]) / 2)
        left, right = np.array(left), np.array(right)
        widths = right - left + 1
        out[path.name] = {
            "pixel_height": int(height),
            "t": ((np.arange(height)[::-1]) / (height - 1)).tolist(),
            "width_over_height": (widths / height).tolist(),
            "centre_over_height": ((np.array(centre) - centre[0]) / height).tolist(),
            "widest_at_t": float((height - 1 - int(np.argmax(widths))) / (height - 1)),
            "width_top_over_max": float(widths[0] / widths.max()),
            "width_bottom_over_max": float(widths[-1] / widths.max()),
        }
    return out


# ------------------------------------------------------------------ main ---


def main() -> None:
    vertices, groups = load_base_mesh()
    vertices = vertices * config.MAKEHUMAN_UNIT_MM
    height = float(np.ptp(vertices[:, 1]))
    low, high = config.MAKEHUMAN_HEIGHT_RANGE_MM
    if not low <= height <= high:
        raise SystemExit(f"base mesh is {height:.0f} mm tall — units are not decimetres")

    body = triangulate(groups[config.MAKEHUMAN_BODY_GROUP])
    knee = joint_centre(vertices, groups, config.MAKEHUMAN_KNEE_JOINT)
    ankle = joint_centre(vertices, groups, config.MAKEHUMAN_ANKLE_JOINT)

    mesh = trimesh.Trimesh(vertices, body, process=True)
    for _ in range(config.SUBDIVIDE_ITERATIONS):
        mesh = trimesh.Trimesh(*trimesh.remesh.subdivide_loop(mesh.vertices, mesh.faces), process=False)

    # Toes are toward +z in this mesh, so that is the front of the leg.
    rotation = shank_frame(knee, ankle, np.array([0.0, 0.0, 1.0]))
    local = (np.asarray(mesh.vertices) - ankle) @ rotation.T
    length = float(np.linalg.norm(knee - ankle))

    axial = local[:, 2]
    radial = np.linalg.norm(local[:, :2], axis=1)
    top = length + config.KNEE_EXTENSION_MM
    keep = (axial > -5) & (axial < top + 5) & (radial < config.SHANK_RADIUS_MM)
    faces = np.asarray(mesh.faces)[keep[np.asarray(mesh.faces)].all(axis=1)]
    shank = trimesh.Trimesh(local, faces, process=False)
    shank.remove_unreferenced_vertices()
    shank = max(shank.split(only_watertight=False), key=lambda m: len(m.faces))
    shank.export(config.WORK / "stage3_shank.stl")

    sv = np.asarray(shank.vertices)
    sampled = length + config.KNEE_EXTENSION_MM
    knee_t = length / sampled
    # Stop a little short of the top: the last slice sits on the cut face of
    # the crop, where the section is clipped rather than measured.
    ts = np.linspace(0.0, 0.97, config.SHANK_SLICES)
    slab = sampled / (config.SHANK_SLICES - 1) / 2
    rows, shapes = [], []
    for t in ts:
        z = t * sampled
        cut = section_points(shank, min(max(z, 0.5), sampled - 0.5))
        if cut is None:
            cut = sv[np.abs(sv[:, 2] - z) <= slab][:, :2]
        contour = star_contour(cut, config.CONTOUR_BINS)
        if contour is None:
            raise SystemExit(f"no shank surface at t={t:.2f}")
        centred = contour - contour.mean(axis=0)
        radii = np.linalg.norm(centred, axis=1)
        shapes.append(radii / radii.mean())
        rows.append({
            "t": round(float(t), 3),
            "width_mm": round(float(np.ptp(contour[:, 0])), 1),
            "thickness_mm": round(float(np.ptp(contour[:, 1])), 1),
            "thickness_over_width": round(float(np.ptp(contour[:, 1]) / np.ptp(contour[:, 0])), 3),
            "mean_radius_mm": round(float(radii.mean()), 1),
            "centre_y_mm": round(float(contour[:, 1].mean()), 1),
        })

    shapes = np.array(shapes)
    np.savez(
        config.WORK / "stage3_profile.npz",
        t=ts,
        knee_t=np.array(knee_t),
        sampled_mm=np.array(sampled),
        shank_mm=np.array(length),
        shape=shapes,
        mean_radius=np.array([r["mean_radius_mm"] for r in rows]),
        thickness_over_width=np.array([r["thickness_over_width"] for r in rows]),
        centre_y=np.array([r["centre_y_mm"] for r in rows]),
        angles=np.linspace(-np.pi, np.pi, config.CONTOUR_BINS, endpoint=False) + np.pi / config.CONTOUR_BINS,
    )

    below_knee = [i for i, r in enumerate(rows) if r["t"] <= knee_t]
    widest = max(below_knee, key=lambda i: rows[i]["mean_radius_mm"])
    report = {
        "source": config.MAKEHUMAN_URL,
        "licence": "CC0 (stated in the file header, September 2020)",
        "base_vertices": int(len(vertices)),
        "body_quads": int(len(groups[config.MAKEHUMAN_BODY_GROUP])),
        "model_height_mm": round(height, 1),
        "units": "decimetres in the file, scaled to mm",
        "subdivided_faces": int(len(mesh.faces)),
        "knee_joint_mm": knee.round(1).tolist(),
        "ankle_joint_mm": ankle.round(1).tolist(),
        "shank_length_mm": round(length, 1),
        "sampled_length_mm": round(sampled, 1),
        "knee_at_t": round(knee_t, 3),
        "widest_at_t": round(float(ts[widest]), 3),
        "widest_mean_radius_mm": rows[widest]["mean_radius_mm"],
        "sections": rows,
        "reference": reference_silhouettes() or "ref_1.png / ref_2.png not in data/",
    }
    (config.WORK / "stage3.json").write_text(json.dumps(report, indent=2))

    draw(shank, rows, shapes, ts, report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("sections", "reference")}, indent=2))
    print("reference:", "extracted" if isinstance(report["reference"], dict) else report["reference"])


def draw(shank, rows, shapes, ts, report) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    v, f = np.asarray(shank.vertices), np.asarray(shank.faces)
    paths = []
    for view in ("side", "front", "three_quarter"):
        path = config.RENDERS / f"stage3_{view}.png"
        render.render([(v, f, config.PART_COLOURS["foot_adapter"])], view, path,
                      title=f"stage 3 — MakeHuman shank, {view.replace('_', ' ')}")
        paths.append(path)
    render.contact_sheet(paths, config.RENDERS / "stage3_sheet.png", columns=3)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2), constrained_layout=True)
    axes[0].plot([r["thickness_over_width"] for r in rows], ts)
    axes[0].set_xlabel("thickness / width"); axes[0].set_ylabel("t   0 = ankle, 1 = knee")
    axes[0].grid(alpha=0.3); axes[0].set_title("section aspect ratio")

    axes[1].plot([r["mean_radius_mm"] for r in rows], ts, label="mean radius")
    axes[1].axhline(report["widest_at_t"], color="crimson", lw=1,
                    label=f"calf widest, t = {report['widest_at_t']:.2f}")
    axes[1].set_xlabel("mm"); axes[1].grid(alpha=0.3); axes[1].legend()
    axes[1].set_title("size along the shank (proportion only)")

    for i in range(0, len(ts), 5):
        angles = np.linspace(-np.pi, np.pi, shapes.shape[1], endpoint=False)
        r = shapes[i]
        axes[2].plot(np.append(r * np.cos(angles), r[0]), np.append(r * np.sin(angles), 0),
                     lw=1, color=plt.cm.viridis(ts[i]), label=f"t={ts[i]:.2f}")
    axes[2].set_aspect("equal"); axes[2].grid(alpha=0.3); axes[2].legend(fontsize=7)
    axes[2].set_xlabel("medio-lateral / mean radius"); axes[2].set_ylabel("fore-aft, + forward")
    axes[2].set_title("section shape, normalised")
    fig.savefig(config.RENDERS / "stage3_profiles.png", dpi=130)


if __name__ == "__main__":
    main()
