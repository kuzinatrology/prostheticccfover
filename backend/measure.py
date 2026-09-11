"""Independent measurements of a finished pattern.

Nothing in here is used to build anything. It exists so the tests can check
the printability rules with geometry that does not reuse the generator's own
parameter-square arithmetic: every number below is measured on the real 3D
positions of the hole boundaries.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Polygon
from shapely.ops import polylabel

from .surface import Surface

SAMPLE_MM = 0.4
"""Boundaries are resampled to about this spacing before measuring gaps."""


def _densify(surface: Surface, ring: np.ndarray) -> np.ndarray:
    p = surface.point(ring[:, 0], ring[:, 1])
    edge = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1)
    steps = int(np.clip(np.ceil(edge.max() / SAMPLE_MM), 1, 64))
    a, b = ring, np.roll(ring, -1, axis=0)
    out = [a * (1 - t) + b * t for t in np.linspace(0.0, 1.0, steps, endpoint=False)]
    q = np.vstack(out)
    return surface.point(q[:, 0], q[:, 1])


def min_strut(surface: Surface, holes: list[np.ndarray]) -> float:
    """Narrowest bridge of material between two different holes, in mm."""
    if len(holes) < 2:
        return float("inf")
    chunks = [_densify(surface, r) for r in holes]
    owner = np.concatenate([np.full(len(c), i) for i, c in enumerate(chunks)])
    pts = np.vstack(chunks)
    tree = cKDTree(pts)
    k = min(48, len(pts))
    d, idx = tree.query(pts, k=k)
    best = np.inf
    for col in range(1, k):
        other = owner[idx[:, col]] != owner
        if other.any():
            best = min(best, float(d[:, col][other].min()))
    return best


def hole_spans(surface: Surface, holes: list[np.ndarray]) -> np.ndarray:
    """Inscribed diameter of every hole, in mm.

    Each ring is dropped onto its own best-fit plane before measuring, so the
    number comes from the 3D positions rather than from the (u, v) square.
    Flattening a curved ring shortens it slightly, which makes this a mild
    underestimate.
    """
    spans = []
    for ring in holes:
        p = surface.point(ring[:, 0], ring[:, 1])
        centre = p.mean(axis=0)
        _, _, vh = np.linalg.svd(p - centre, full_matrices=False)
        flat = (p - centre) @ vh[:2].T
        poly = Polygon(flat)
        if not poly.is_valid or poly.area <= 0:
            continue
        pt = polylabel(poly, tolerance=0.02 * np.sqrt(poly.area))
        spans.append(2.0 * poly.exterior.distance(pt))
    return np.array(spans)


def surface_area(surface: Surface, nu: int = 192, nv: int = 240) -> float:
    """Area of the outer surface in mm^2, by summing the grid quads."""
    points, _ = surface.grid(nu, nv)
    a = points[:-1, :, :]
    b = np.roll(points, -1, axis=1)[:-1, :, :]
    c = np.roll(points, -1, axis=1)[1:, :, :]
    d = points[1:, :, :]
    return float(
        (
            np.linalg.norm(np.cross(b - a, c - a), axis=-1)
            + np.linalg.norm(np.cross(c - a, d - a), axis=-1)
        ).sum()
        / 2.0
    )


def hole_area(surface: Surface, holes: list[np.ndarray]) -> float:
    """Total area of the openings in mm^2, measured on the real 3D rings."""
    total = 0.0
    for ring in holes:
        p = surface.point(ring[:, 0], ring[:, 1])
        # Newell's formula: the area of a nearly planar 3D polygon.
        total += 0.5 * float(np.linalg.norm(np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0)))
    return total


def wall_thickness_samples(
    mesh, surface: Surface, count: int = 240, seed: int = 3, reach: float = 12.0
) -> np.ndarray:
    """Wall thickness in mm, probed by firing rays through the cover.

    A ray aimed at the axis from well outside crosses the near wall twice, and
    the gap between those two crossings is the wall. Nothing about how the mesh
    was built is used, so this measures the object rather than the recipe.
    """
    from . import mesh_build

    rng = np.random.default_rng(seed)
    u = rng.random(count)
    v = rng.uniform(0.12, 0.88, count)
    point, normal = surface.frame(u, v)
    solid = mesh_build.to_manifold(mesh)

    span = 2.0 * reach
    out = []
    for start, direction in zip(point + normal * reach, -normal):
        hits = solid.ray_cast(start.tolist(), (start + direction * span).tolist())
        if len(hits) >= 2:
            # A hit reports how far along the segment it landed, not millimetres.
            out.append((hits[1].distance - hits[0].distance) * span)
    return np.array(out)
