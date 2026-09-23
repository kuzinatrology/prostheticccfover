"""A cover at a fraction of its size, with everything else left in millimetres.

A prototype is printed smaller than the leg, but a wall, a magnet and a clamp
are not smaller: the wall has to print, the magnet is a part off a shelf, and
the clamp goes round a real 34 mm tube.  Scaling a finished cover would take
them all down with it.

So the *surface* is scaled and nothing else is.  Everything built on it after
that is asked for in millimetres and comes out in millimetres, and the holes
are carried over unchanged -- a hole is a ring in the surface's own (u, v)
coordinates, and those do not know how big the surface is.  The pattern
therefore lands exactly where it landed on the full-size cover.
"""

from __future__ import annotations

import numpy as np

from ..surface import SurfaceBase


class ScaledSurface(SurfaceBase):
    """`base`, shrunk about the origin by `factor`.

    The origin is where the cover's own frame puts it -- the axis at the
    bottom rim -- so scaling about it keeps the cover standing on z = 0 and
    keeps its axis where it was.
    """

    def __init__(self, base, factor: float) -> None:
        self.base = base
        self.factor = float(factor)
        self.length = base.length * self.factor

    # --- what the shell and the prisms ask ---------------------------------

    def point(self, u, v) -> np.ndarray:
        return self.base.point(u, v) * self.factor

    def radius(self, v):
        return self.base.radius(v) * self.factor

    def semi_axes(self, v):
        a, b = self.base.semi_axes(v)
        return a * self.factor, b * self.factor

    def min_curvature_radius(self) -> float:
        return self.base.min_curvature_radius() * self.factor

    # --- what the fasteners ask --------------------------------------------

    @property
    def data(self):
        return self.base.data

    @property
    def wall(self) -> float:
        return self.base.wall

    def _up(self, z):
        """A height on this surface, as a height on the one it came from."""
        return np.asarray(z, dtype=float) / self.factor

    def radial(self, theta, z):
        return self.base.radial(theta, self._up(z)) * self.factor

    def centre(self, z) -> np.ndarray:
        return np.atleast_2d(self.base.centre(self._up(z))) * self.factor

    def star_centre(self, z) -> np.ndarray:
        return np.atleast_2d(self.base.star_centre(self._up(z))) * self.factor

    def z_of_v(self, v):
        return self.base.z_of_v(v) * self.factor

    def v_of_z(self, z):
        return self.base.v_of_z(self._up(z))

    def rim(self, u):
        return self.base.rim(u) * self.factor

    def foot(self, u):
        return self.base.foot(u) * self.factor

    def edge_distance(self, u, v):
        return self.base.edge_distance(u, v) * self.factor

    def loft_grid(self, rows: int) -> np.ndarray:
        return self.base.loft_grid(rows) * self.factor

    def curvature_radii(self, *a, **kw):
        return self.base.curvature_radii(*a, **kw) * self.factor

    def offset_grid(self, grid: np.ndarray, distance) -> np.ndarray:
        """Move a grid `distance` millimetres, on this surface's own scale.

        The cover underneath only knows its own size, so the distance is taken
        down to that scale, applied there, and brought back -- which lands the
        grid exactly `distance` millimetres from where it started here.  This
        is what keeps the wall a real wall on a small cover.
        """
        d = np.asarray(distance, dtype=float) / self.factor
        return self.base.offset_grid(grid / self.factor, d) * self.factor

    def max_wall_thickness(self, profile, ceiling: float) -> float:
        return SurfaceBase.max_wall_thickness(self, profile, ceiling)
