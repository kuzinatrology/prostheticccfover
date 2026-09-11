"""Relief: the same cell field, raised or sunk instead of cut through.

The wall stays solid, so none of the strut and hole rules apply here at all.
What does apply is that a relief cannot sink deeper than the wall it is cut
into, which is why `relief_depth` has its own moving ceiling.

The height at any point comes from the Voronoi structure without building a
single polygon. For a Voronoi diagram the distance to the cell boundary is
exactly half the gap between the two nearest seeds, so two nearest-neighbour
queries give the whole field.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .fields import Field, as_array_field
from .pattern import RIM_MM, CellField, _tiled

PROFILES = ("dome", "ridge", "bevel")

BEVEL_RUN = 0.35
"""Fraction of the half-cell a bevel takes to climb before it levels off."""

RIDGE_RUN = 0.3
"""Fraction of the half-cell a ridge occupies either side of the boundary."""


def max_depth(wall_thickness: float, engraving: bool, ceiling: float) -> float:
    """The deepest relief this wall can carry.

    Cutting into the wall may take a little over half of it and no more, so
    the slider's own top end moves with the wall. Raising material has no such
    limit, since nothing is removed.
    """
    if not engraving:
        return ceiling
    return min(ceiling, 0.6 * wall_thickness)


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _shape(t: np.ndarray, profile: str) -> np.ndarray:
    """Height from `t`, which is 0 on a cell boundary and 1 at its centre."""
    if profile == "ridge":
        # A bead running along the cell walls, the negative of a dome.
        return 1.0 - _smoothstep(t / RIDGE_RUN)
    if profile == "bevel":
        # A chamfer that climbs off the boundary and then holds a flat top.
        return _smoothstep(t / BEVEL_RUN)
    # A dome: round at the top, meeting the surface squarely at the boundary.
    return np.sqrt(np.clip(1.0 - (1.0 - t) ** 2, 0.0, 1.0))


def height_field(
    cells: CellField,
    mask: Field,
    u: np.ndarray,
    v: np.ndarray,
    *,
    depth: float,
    profile: str,
    length: float,
) -> np.ndarray:
    """Relief height in mm at each (u, v). Same shape as the inputs."""
    if depth <= 0 or len(cells.seeds) < 4:
        return np.zeros_like(np.asarray(u, dtype=float))

    warp, domain = cells.warp, cells.domain
    q_lo, q_hi = domain.V_lo / warp.sy, domain.V_hi / warp.sy

    U = np.asarray(u, dtype=float) * 2.0 * np.pi
    V = domain.V_of_v(np.clip(np.asarray(v, dtype=float), 0.0, 1.0))
    q = V / warp.sy
    p = (U - q * warp.shear) / warp.sx
    p = p % warp.period

    tiled = _tiled(cells.seeds, warp.period, q_lo, q_hi, cells.band)
    query = np.stack([p.ravel(), q.ravel()], axis=1)
    d, _ = cKDTree(tiled).query(query, k=2)
    # For a Voronoi cell the boundary sits exactly halfway between the two
    # nearest seeds, so this is the distance to the cell wall.
    border = (d[:, 1] - d[:, 0]) / 2.0
    spacing = cells.spacing(query[:, 0], query[:, 1])
    t = np.clip(2.0 * border / np.maximum(spacing, 1e-9), 0.0, 1.0)

    h = _shape(t, profile).reshape(np.shape(u))
    h *= as_array_field(mask)(u, v)
    # Let the relief die out before the rim so the openings stay clean.
    margin = min(0.3, RIM_MM / length)
    h *= _smoothstep(np.asarray(v, dtype=float) / margin) * _smoothstep(
        (1.0 - np.asarray(v, dtype=float)) / margin
    )
    return h * depth
