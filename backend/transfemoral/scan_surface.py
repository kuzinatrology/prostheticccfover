"""The scanned leg as a surface the cell field can live on.

Stored as a radius over a grid of (angle, height) about a centreline, which is
exactly the unwrapping the rest of the code already speaks: u is the angle
around the axis, v is height. The scan is star shaped about that axis (every
one of 2808 probe rays crossed it once), so nothing is lost by storing it so.

    point(u, v) = c(z) + R(theta, z) * (cos theta, sin theta, 0),
    theta = 2 pi u,  z = z_bottom + v * length

theta = 0 is +x, theta = pi/2 is the front (+y), theta = 3 pi/2 the back.

Smoothing happens here rather than in preparation, because the smoothing
slider moves it. Whatever the slider says, the surface never moves more than
SMOOTH_MAX_SHIFT from the scan.
"""

from __future__ import annotations

import pathlib
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


def smooth_radius(
    R: np.ndarray, dz: float, strength: float
) -> tuple[np.ndarray, float]:
    """Take skin texture and mesh facets off the radius grid.

    A Gaussian of up to SMOOTH_SIGMA_MAX millimetres, measured as arc length
    around each section and as height along it. The whole correction is then
    scaled down until no sample moves more than SMOOTH_MAX_SHIFT. The normal
    displacement is never more than the radial one, so that bounds it too.

    Returns the smoothed grid and the largest radial shift it applied.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    sigma = strength * cfg.SMOOTH_SIGMA_MAX
    if sigma <= 1e-6:
        return R.copy(), 0.0
    rows, cols = R.shape
    d_theta = TWO_PI / cols
    out = np.empty_like(R)
    for j in range(rows):
        s = sigma / max(float(R[j].mean()) * d_theta, 1e-6)
        out[j] = gaussian_filter1d(R[j], s, mode="wrap")
    out = gaussian_filter1d(out, sigma / dz, axis=0, mode="nearest")
    delta = out - R
    worst = float(np.abs(delta).max())
    if worst > cfg.SMOOTH_MAX_SHIFT:
        delta *= cfg.SMOOTH_MAX_SHIFT / worst
    return R + delta, float(np.abs(delta).max())


@dataclass(frozen=True)
class ScanData:
    theta: np.ndarray
    z: np.ndarray
    R: np.ndarray
    known: np.ndarray
    centre: np.ndarray
    """(rows, 2) centreline x, y at each grid height."""
    tangent: np.ndarray
    """(2,) dx/dz, dy/dz of the straight extension above the trusted part."""
    meta: dict

    @classmethod
    def load(cls, path: pathlib.Path = cfg.SURFACE_FILE) -> ScanData:
        import json

        with np.load(path, allow_pickle=False) as f:
            return cls(
                theta=f["theta"],
                z=f["z"],
                R=f["R"].astype(float),
                known=f["known"],
                centre=f["centre"],
                tangent=f["tangent"],
                meta=json.loads(str(f["meta"])),
            )


@lru_cache(maxsize=1)
def _data() -> ScanData:
    return ScanData.load()


class ScanSurface(SurfaceBase):
    """The scan, trimmed to [bottom, top_z], with a given smoothing."""

    def __init__(self, data: ScanData, smoothing: float):
        self.data = data
        self.z0 = float(data.z[0])
        self.z1 = float(data.z[-1])
        self.length = self.z1 - self.z0
        dz = float(data.z[1] - data.z[0])
        self.R, self.smoothing_shift = smooth_radius(data.R, dz, smoothing)

        cols = len(data.theta)
        th = np.concatenate(
            [data.theta[-PAD:] - TWO_PI, data.theta, data.theta[:PAD] + TWO_PI]
        )
        grid = np.concatenate([self.R[:, -PAD:], self.R, self.R[:, :PAD]], axis=1)
        self._spline = RectBivariateSpline(data.z, th, grid, kx=3, ky=3)
        self._cols = cols

        mean = self.R.mean(axis=1)
        v = (data.z - self.z0) / self.length
        self._mean = PchipInterpolator(v, mean, extrapolate=True)
        self._cx = data.centre[:, 0]
        self._cy = data.centre[:, 1]
        self._min_curvature: float | None = None
        self.region = None
        """Where the cover is: a function of 3D points, True where there is
        material. Set by the generator before anything reads the curvature."""

    @classmethod
    def default(cls, smoothing: float = cfg.SMOOTH_DEFAULT) -> ScanSurface:
        return _surface(round(float(smoothing), 4))

    # --- coordinates -------------------------------------------------------
    def z_of_v(self, v):
        return self.z0 + np.asarray(v, dtype=float) * self.length

    def v_of_z(self, z):
        return (np.asarray(z, dtype=float) - self.z0) / self.length

    def centre(self, z) -> np.ndarray:
        """Centreline at height z, straight beyond both ends of the grid."""
        z = np.asarray(z, dtype=float)
        zc = np.clip(z, self.z0, self.z1)
        x = np.interp(zc, self.data.z, self._cx)
        y = np.interp(zc, self.data.z, self._cy)
        above = np.maximum(z - self.z1, 0.0)
        below = np.minimum(z - self.z0, 0.0)
        tx, ty = self.data.tangent
        # Below the ankle the grid ends; the same straight run carries on.
        x = x + tx * (above + below)
        y = y + ty * (above + below)
        return np.stack([x, y], axis=-1)

    def radial(self, theta, z) -> np.ndarray:
        """R at (theta, z), held at the end rows beyond the grid."""
        theta = np.asarray(theta, dtype=float) % TWO_PI
        zc = np.clip(np.asarray(z, dtype=float), self.z0, self.z1)
        theta, zc = np.broadcast_arrays(theta, zc)
        return self._spline.ev(zc.ravel(), theta.ravel()).reshape(theta.shape)

    # --- SurfaceBase ---------------------------------------------------------
    def radius(self, v):
        return self._mean(np.clip(np.asarray(v, dtype=float), 0.0, 1.0))

    def point(self, u, v) -> np.ndarray:
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        u, v = np.broadcast_arrays(u, v)
        theta = TWO_PI * u
        z = self.z_of_v(v)
        r = self.radial(theta, z)
        c = self.centre(z)
        return np.stack(
            [c[..., 0] + r * np.cos(theta), c[..., 1] + r * np.sin(theta), z], axis=-1
        )

    def semi_axes(self, v):
        """Half-widths of the section, for the few callers that want a size."""
        v = np.atleast_1d(np.asarray(v, dtype=float))
        theta = np.linspace(0.0, TWO_PI, 72, endpoint=False)
        r = self.radial(theta[None, :], self.z_of_v(v)[:, None])
        return r.min(axis=1), r.max(axis=1)

    def uv_of_point(self, p: np.ndarray) -> np.ndarray:
        """(u, v) of points near the surface, by their angle about the axis."""
        p = np.asarray(p, dtype=float)
        c = self.centre(p[..., 2])
        theta = np.arctan2(p[..., 1] - c[..., 1], p[..., 0] - c[..., 0]) % TWO_PI
        return np.stack([theta / TWO_PI, self.v_of_z(p[..., 2])], axis=-1)

    def curvature_radii(self, rows: int = 160, around: int = 720) -> np.ndarray:
        """Convex radius of curvature at every sample, inf where concave.

        Only an outward bulge folds an inward offset or bends a hole into the
        far wall, so a hollow does not count. Measured around each section and
        along each meridian by the circle through three points
        CURVATURE_BASELINE apart, and the tighter of the two is kept.

        The baseline is the point. The scan is a mesh of eight millimetre
        triangles and every one of its corners is a kink a millimetre across;
        read point by point it has a radius of two millimetres, which would cap
        the wall and every hole at nothing. Nothing the cover does happens on
        that scale. Samples outside `self.region`, the notch, are not read.
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
            r_section[j] = _circle_radius(np.roll(xy[j], k, axis=0), xy[j], np.roll(xy[j], -k, axis=0))

        c = self.centre(p[..., 2])
        rho = np.linalg.norm(xy - c, axis=-1)
        meridian = np.stack([rho, p[..., 2]], axis=-1)
        step = max(1, int(round(base / (self.length / (rows - 1)))))
        r_meridian = np.full(uu.shape, np.inf)
        # Walking up with the outside on the right: positive turn is convex.
        r_meridian[step:-step] = _circle_radius(
            meridian[: -2 * step], meridian[step:-step], meridian[2 * step :], clockwise=True
        )
        out = np.minimum(r_section, r_meridian)
        if self.region is not None:
            out = np.where(self.region(p), out, np.inf)
        return out

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


@lru_cache(maxsize=8)
def _surface(smoothing: float) -> ScanSurface:
    return ScanSurface(_data(), smoothing)

