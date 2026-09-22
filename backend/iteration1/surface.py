"""The Rhino cover as a surface the cell field can live on.

Stored by `prepare.py` as an outer radius over a grid of (angle, height) about
a centreline, which is the unwrapping the rest of the code already speaks: u is
the angle around the axis, v is height.

    point(u, v) = c(z) + R(theta, z) * (cos theta, sin theta, 0),
    theta = 2 pi u,  z = z_bottom + v * length

Two curves come with it, and they are what makes this cover different from a
tube: `foot(u)` and `rim(u)`, the heights of the bottom and top rims at each
angle.  The top one runs from 323 mm at the back of the knee to 457 at the
sides, and every field that decides where material and holes may go is read
from it.

Smoothing happens here rather than in preparation, because the smoothing
slider moves it.  Whatever the slider says, the surface never moves more than
SMOOTH_MAX_SHIFT from the file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.interpolate import PchipInterpolator, RectBivariateSpline
from scipy.ndimage import gaussian_filter1d

from ..surface import TWO_PI, SurfaceBase
from . import config as cfg

PAD = 4
"""Columns wrapped onto either side of the angle grid so the spline is
periodic in effect."""


def smooth_radius(R: np.ndarray, dz: float, strength: float) -> tuple[np.ndarray, float]:
    """Take the facets of a coarse export off the radius grid.

    A Gaussian of up to SMOOTH_SIGMA_MAX millimetres, measured as arc length
    around each section and as height along it.  The whole correction is then
    scaled down until no sample moves more than SMOOTH_MAX_SHIFT, so the cover
    stays the one that was modelled.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    sigma = strength * cfg.SMOOTH_SIGMA_MAX
    if sigma <= 1e-6:
        return R.copy(), 0.0
    rows, cols = R.shape
    d_theta = TWO_PI / cols
    out = np.empty_like(R)
    for j in range(rows):
        out[j] = gaussian_filter1d(R[j], sigma / max(float(R[j].mean()) * d_theta, 1e-6), mode="wrap")
    out = gaussian_filter1d(out, sigma / dz, axis=0, mode="nearest")
    delta = out - R
    worst = float(np.abs(delta).max())
    if worst > cfg.SMOOTH_MAX_SHIFT:
        delta *= cfg.SMOOTH_MAX_SHIFT / worst
    return R + delta, float(np.abs(delta).max())


@dataclass(frozen=True)
class CoverData:
    theta: np.ndarray
    z: np.ndarray
    R: np.ndarray
    W: np.ndarray
    known: np.ndarray
    centre: np.ndarray
    bottom: np.ndarray
    top: np.ndarray
    meta: dict

    @classmethod
    def load(cls, path=None) -> CoverData:
        with np.load(path or cfg.SURFACE_FILE, allow_pickle=False) as f:
            return cls(
                theta=f["theta"],
                z=f["z"],
                R=f["R"].astype(float),
                W=f["W"].astype(float),
                known=f["known"],
                centre=f["centre"],
                bottom=f["bottom"],
                top=f["top"],
                meta=json.loads(str(f["meta"])),
            )


@lru_cache(maxsize=8)
def _data(model: str | None = None) -> CoverData:
    return CoverData.load(cfg.model(model).surface_file)


@dataclass(frozen=True)
class Shape:
    """What the sliders are allowed to do to the modelled shape.

    The file decides the cover; these decide how it is worn.  Every one of
    them is a transformation of the measured surface, so none of them can
    invent a shape the model does not have — a fuller cover is this cover
    fuller, and a deeper notch is this notch deeper.  All neutral is the file
    as it was drawn.
    """

    fullness: float = 1.0
    """Girth, as a multiple of the model's."""
    ovality: float = 1.0
    """Section squashed front to back (below one) or side to side (above)."""
    posterior_bias: float = 0.0
    """How much of the cover's swell is carried behind the axis."""
    twist: float = 0.0
    """Degrees the section turns between the bottom rim and the top."""
    height_scale: float = 1.0
    """The cover stretched along its own axis, anchored at the bottom rim."""
    top_trim: float = 0.0
    """Millimetres taken off the top rim, all the way round."""
    bottom_trim: float = 0.0
    """Millimetres taken off the bottom rim."""
    notch_deepen: float = 0.0
    """Millimetres the back notch goes deeper, in proportion to how much of a
    notch the rim already is there: the deepest point moves by all of it and
    the high sides do not move at all."""


NEUTRAL = Shape()

MIN_STANDING = 30.0
"""The shortest column the trims may leave, mm.  Past this the two rims would
cross and the cover would turn itself inside out."""


class IterSurface(SurfaceBase):
    """The modelled cover's outer skin, smoothed and shaped."""

    def __init__(self, data: CoverData, smoothing: float, shape: Shape = NEUTRAL):
        self.data = data
        self.shape = shape
        dz = float(data.z[1] - data.z[0])
        self.R, self.smoothing_shift = smooth_radius(data.R, dz, smoothing)
        self.wall = float(data.meta["wall_mm"])

        th = np.concatenate([data.theta[-PAD:] - TWO_PI, data.theta, data.theta[:PAD] + TWO_PI])
        grid = np.concatenate([self.R[:, -PAD:], self.R, self.R[:, :PAD]], axis=1)
        self._spline = RectBivariateSpline(data.z, th, grid, kx=3, ky=3)

        # --- where the two rims end up ------------------------------------
        # The height scale is anchored at the model's bottom rim; the trims
        # then cut the ends rather than stretch what is between them.
        self._anchor = float(data.bottom.min())
        top, bottom = data.top, data.bottom
        span = float(np.ptp(top))
        # How much of a notch the rim already is at each angle, 0 at its
        # highest and 1 at its lowest.
        depth = (top.max() - top) / span if span > 1e-6 else np.zeros_like(top)
        self._foot = self._to_world(bottom) + shape.bottom_trim
        self._rim = self._to_world(top) - shape.top_trim - shape.notch_deepen * depth
        self._rim = np.maximum(self._rim, self._foot + MIN_STANDING)

        self.z0 = float(self._foot.min())
        self.z1 = float(self._rim.max())
        self.length = self.z1 - self.z0

        mean = self.R.mean(axis=1)
        self._swell = mean - float(mean.min())
        v = np.clip((self._to_world(data.z) - self.z0) / self.length, -1.0, 2.0)
        self._mean = PchipInterpolator(v, mean * shape.fullness, extrapolate=True)
        self._swell_at = PchipInterpolator(data.z, self._swell, extrapolate=True)
        self._min_curvature: float | None = None

    @classmethod
    def default(cls, smoothing: float = 0.0, shape: Shape = NEUTRAL,
                model: str | None = None) -> IterSurface:
        return _surface(round(float(smoothing), 4), shape, model or cfg.DEFAULT_MODEL)

    # --- coordinates -------------------------------------------------------
    def _to_world(self, z_model):
        """A height in the file, in the cover's own coordinates."""
        return self._anchor + (np.asarray(z_model, dtype=float) - self._anchor) * self.shape.height_scale

    def _to_model(self, z) -> np.ndarray:
        """...and back, so the file can be read at a height of the cover."""
        z = self._anchor + (np.asarray(z, dtype=float) - self._anchor) / self.shape.height_scale
        return np.clip(z, self.data.z[0], self.data.z[-1])

    def z_of_v(self, v):
        return self.z0 + np.asarray(v, dtype=float) * self.length

    def v_of_z(self, z):
        return (np.asarray(z, dtype=float) - self.z0) / self.length

    def centre(self, z) -> np.ndarray:
        """The file's centreline, at a height of the file."""
        z = np.clip(np.asarray(z, dtype=float), self.data.z[0], self.data.z[-1])
        return np.stack(
            [np.interp(z, self.data.z, self.data.centre[:, i]) for i in range(2)], axis=-1
        )

    def radial(self, theta, z) -> np.ndarray:
        """The radius the file has at (theta, its own height).

        The shape knobs are not in here: this is the measurement, and it is
        what the tests compare the stored surface with.
        """
        theta = np.asarray(theta, dtype=float) % TWO_PI
        zc = np.clip(np.asarray(z, dtype=float), self.data.z[0], self.data.z[-1])
        theta, zc = np.broadcast_arrays(theta, zc)
        return self._spline.ev(zc.ravel(), theta.ravel()).reshape(theta.shape)

    # --- the shape, as the sliders leave it --------------------------------
    def _turn(self, z):
        """The section's turn at this height, radians."""
        if self.shape.twist == 0.0:
            return np.zeros_like(np.asarray(z, dtype=float))
        return np.radians(self.shape.twist) * np.clip(self.v_of_z(z), 0.0, 1.0)

    def _place(self, theta, z) -> tuple[np.ndarray, np.ndarray]:
        """Where (theta, height) lands on the shaped skin, in x and y.

        Girth, ovality and the backward carry are applied to the section about
        its own centre, and the twist turns the result; the order matters, and
        it is the transtibial surface's order, so a design reads the same on
        this cover as on that one.
        """
        theta = np.asarray(theta, dtype=float)
        z = np.asarray(z, dtype=float)
        theta, z = np.broadcast_arrays(theta, z)
        zm = self._to_model(z)
        r = self.radial(theta, zm) * self.shape.fullness
        k = np.sqrt(self.shape.ovality)
        x0 = r * np.cos(theta) / k
        y0 = r * np.sin(theta) * k - self._carry(zm)
        turn = self._turn(z)
        ct, st = np.cos(turn), np.sin(turn)
        c = self.centre(zm)
        return c[..., 0] + x0 * ct - y0 * st, c[..., 1] + x0 * st + y0 * ct

    def _carry(self, z_model) -> np.ndarray:
        """How far back the section slides at this height, mm.

        Proportional to how much of the cover's girth there is calf: at a bias
        of one the front of the shank stays where it was and all of the swell
        is behind it.
        """
        if self.shape.posterior_bias == 0.0:
            return np.zeros_like(np.asarray(z_model, dtype=float))
        return self.shape.posterior_bias * self.shape.fullness * self._swell_at(z_model)

    def star_centre(self, z) -> np.ndarray:
        """The point each section is star shaped about, after shaping."""
        z = np.asarray(z, dtype=float)
        zm = self._to_model(z)
        carry = self._carry(zm)
        turn = self._turn(z)
        ct, st = np.cos(turn), np.sin(turn)
        c = self.centre(zm)
        return np.stack([c[..., 0] + carry * st, c[..., 1] - carry * ct], axis=-1)

    # --- the two rims ------------------------------------------------------
    def _rim_at(self, curve: np.ndarray, u) -> np.ndarray:
        """A rim curve read at any angle, periodic."""
        u = np.asarray(u, dtype=float) % 1.0
        theta = self.data.theta
        wrapped = np.concatenate([theta - TWO_PI, theta, theta + TWO_PI])
        values = np.tile(curve, 3)
        return np.interp(TWO_PI * u, wrapped, values)

    def rim(self, u) -> np.ndarray:
        """Height of the top rim, mm."""
        return self._rim_at(self._rim, u)

    def foot(self, u) -> np.ndarray:
        """Height of the bottom rim, mm."""
        return self._rim_at(self._foot, u)

    def edge_distance(self, u, v) -> np.ndarray:
        """How far a point is from the nearer rim, mm; negative past it.

        Measured as height, which on a cover whose walls stand within a few
        degrees of vertical is the distance along the surface to within a
        percent, and always the shorter of the two.
        """
        z = self.z_of_v(v)
        return np.minimum(z - self.foot(u), self.rim(u) - z)

    # --- SurfaceBase -------------------------------------------------------
    def radius(self, v):
        return self._mean(np.clip(np.asarray(v, dtype=float), 0.0, 1.0))

    def point(self, u, v) -> np.ndarray:
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        u, v = np.broadcast_arrays(u, v)
        z = self.z_of_v(v)
        x, y = self._place(TWO_PI * u, z)
        return np.stack([x, y, z], axis=-1)

    def semi_axes(self, v):
        v = np.atleast_1d(np.asarray(v, dtype=float))
        theta = np.linspace(0.0, TWO_PI, 72, endpoint=False)
        z = self.z_of_v(v)[:, None]
        x, y = self._place(theta[None, :], z)
        c = self.star_centre(z)
        r = np.hypot(x - c[..., 0], y - c[..., 1])
        return r.min(axis=1), r.max(axis=1)

    def normal(self, theta, z, step: float = 0.5) -> np.ndarray:
        """Outward unit normal at (theta, height), from the shaped surface.

        By differencing the surface itself rather than by averaging the faces
        of a mesh built over it.  The grid's rows are laid column by column
        between that column's two rims, so along the top rim the rows of
        neighbouring columns are at different heights and a normal averaged
        from the faces there swings by tens of degrees from one column to the
        next — a rim of spikes, once the inner skin is offset along it.
        Differencing in (theta, height) knows nothing about where a column
        ends, so it is as steady on the rim as in the middle.
        """
        theta = np.asarray(theta, dtype=float)
        z = np.asarray(z, dtype=float)
        theta, z = np.broadcast_arrays(theta, z)
        radius = np.maximum(np.mean(self.radial(theta, self._to_model(z))), 1.0)
        d_theta = step / radius

        def at(t, h):
            x, y = self._place(t, h)
            return np.stack([x, y, np.broadcast_to(h, x.shape)], -1)

        along_theta = (at(theta + d_theta, z) - at(theta - d_theta, z)) / (2 * d_theta)
        along_z = (at(theta, z + step) - at(theta, z - step)) / (2 * step)
        n = np.cross(along_theta, along_z)
        n = n / np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-12)
        here = at(theta, z)
        out = here[..., :2] - self.star_centre(z)
        out = out / np.maximum(np.linalg.norm(out, axis=-1, keepdims=True), 1e-12)
        facing = np.einsum("...i,...i->...", n[..., :2], out)
        return np.where(facing[..., None] < 0.0, -n, n)

    # --- the solid ---------------------------------------------------------
    def loft_grid(self, rows: int) -> np.ndarray:
        """The outer skin as an (rows, cols, 3) grid, column by column.

        Every column runs from its own foot to its own rim, so the top edge of
        the grid *is* the rim curve and the cover ends on it exactly, rather
        than on a staircase of triangle edges.
        """
        theta = self.data.theta
        cols = len(theta)
        u = (theta % TWO_PI) / TWO_PI
        foot, rim = self.foot(u), self.rim(u)
        steps = np.linspace(0.0, 1.0, rows)[:, None]
        z = foot[None, :] + (rim - foot)[None, :] * steps
        x, y = self._place(np.broadcast_to(theta, z.shape), z)
        return np.stack([x, y, z], axis=-1)

    def offset_grid(self, grid: np.ndarray, distance) -> np.ndarray:
        """A grid moved `distance` across the skin: inward if negative.

        Out from the section's centre, not along the normal.  The cover is
        star shaped about its axis and its walls stand within a few degrees of
        vertical, so a smaller radius is what a wall inward means.  Offsetting
        along the normal is what a general solid would need, and it is exactly
        what goes wrong on this one: over the rim the normal turns up across
        the edge, and a skin offset along it climbs above the rim and crosses
        the skin it was offset from — a rim of spikes.  How much of the normal
        lies along the radius is divided back out, so the wall measured across
        the skin is the one that was asked for, and it is clamped because
        where the surface does turn over the correction would run away.
        """
        theta = np.broadcast_to(self.data.theta, grid.shape[:2])
        z = grid[..., 2]
        centre = self.star_centre(z)
        out = grid[..., :2] - centre
        r = np.linalg.norm(out, axis=-1)
        direction = out / np.maximum(r[..., None], 1e-12)
        u = (theta % TWO_PI) / TWO_PI
        lo, hi = self.foot(u) + cfg.WALL_PROBE, self.rim(u) - cfg.WALL_PROBE
        probe = np.where(hi > lo, np.clip(z, lo, hi), (self.foot(u) + self.rim(u)) / 2.0)
        normal = self.normal(theta, probe)
        frac = np.einsum("...i,...i->...", normal[..., :2], direction)
        # Read column by column off a one degree grid, the lean carries the
        # grid's own scatter with it, and a wall that changes by a tenth of a
        # millimetre from one column to the next is a rippled rim band.  The
        # lean of a cover does not change that fast.
        frac = gaussian_filter1d(frac, cfg.WALL_LEAN_SMOOTH_DEG, axis=-1, mode="wrap")
        frac = np.clip(frac, cfg.WALL_LEAN_FLOOR, 1.0)
        moved = np.maximum(r + np.asarray(distance) / frac, 0.5)
        return np.stack(
            [centre[..., 0] + moved * direction[..., 0],
             centre[..., 1] + moved * direction[..., 1], z], axis=-1
        )

    # --- printability ------------------------------------------------------
    def curvature_radii(self, rows: int = 160, around: int = 720) -> np.ndarray:
        """Convex radius of curvature at every sample, inf where concave.

        Only an outward bulge folds an inward offset or bends a hole into the
        far wall, so a hollow does not count.  Read over CURVATURE_BASELINE
        rather than point to point: the export is a mesh of several millimetre
        triangles and every corner of it is a kink a millimetre across.
        Samples past a rim are not read; the cover is not there.
        """
        base = cfg.CURVATURE_BASELINE
        v = np.linspace(0.0, 1.0, rows)
        u = np.linspace(0.0, 1.0, around, endpoint=False)
        uu, vv = np.meshgrid(u, v)
        p = self.point(uu, vv)

        xy = p[..., :2]
        spacing = np.linalg.norm(np.roll(xy, -1, axis=1) - xy, axis=-1).mean(axis=1)
        r_section = np.full(uu.shape, np.inf)
        for j in range(rows):
            k = max(1, int(round(base / max(spacing[j], 1e-6))))
            r_section[j] = _circle_radius(
                np.roll(xy[j], k, axis=0), xy[j], np.roll(xy[j], -k, axis=0)
            )

        c = self.star_centre(p[..., 2])
        rho = np.linalg.norm(xy - c, axis=-1)
        meridian = np.stack([rho, p[..., 2]], axis=-1)
        step = max(1, int(round(base / (self.length / (rows - 1)))))
        r_meridian = np.full(uu.shape, np.inf)
        r_meridian[step:-step] = _circle_radius(
            meridian[: -2 * step], meridian[step:-step], meridian[2 * step :], clockwise=True
        )
        out = np.minimum(r_section, r_meridian)
        return np.where(self.edge_distance(uu, vv) > 0.0, out, np.inf)

    def min_curvature_radius(self) -> float:
        if self._min_curvature is None:
            self._min_curvature = float(np.min(self.curvature_radii()))
        return self._min_curvature


def _circle_radius(a: np.ndarray, b: np.ndarray, c: np.ndarray, clockwise: bool = False) -> np.ndarray:
    """Radius of the circle through three 2D points, inf where it turns inward."""
    ab = np.linalg.norm(a - b, axis=-1)
    bc = np.linalg.norm(b - c, axis=-1)
    ca = np.linalg.norm(c - a, axis=-1)
    cross = (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (
        c[..., 0] - a[..., 0]
    )
    if clockwise:
        cross = -cross
    radius = ab * bc * ca / np.maximum(2.0 * np.abs(cross), 1e-12)
    return np.where(cross > 1e-12, radius, np.inf)


@lru_cache(maxsize=16)
def _surface(smoothing: float, shape: Shape, model: str) -> IterSurface:
    return IterSurface(_data(model), smoothing, shape)
