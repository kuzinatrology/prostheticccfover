"""The anatomic cover's outer skin, as a surface the cell field can live on.

Stage 4 of the anatomic pipeline leaves the cover as a radius over (angle,
height) about a centre line, plus the rim curve.  That is the unwrapping the
pattern already speaks — u the angle, v the height — with one twist: v does
not run to a flat top.  Every column of the square ends on the rim, so v = 1
*is* the rim.  The notch then needs no boolean, the shell closes along it, and
the pattern's own edge fade follows the cut instead of ignoring it.

    point(u, v) = c(z) + R(theta, z) * (cos theta, sin theta, 0)
    theta = 2 pi u,  z = bottom + v * (rim(theta) - bottom)

theta = 0 is +x, pi/2 is the front of the leg, 3 pi/2 the back.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import RectBivariateSpline

from .surface import TWO_PI, SurfaceBase

CURVATURE_BASELINE = 3.0
"""Millimetres between the three points a radius of curvature is read from."""

PAD = 4
"""Columns wrapped onto either side of the angle grid so the spline is
periodic in effect."""


class AnatomicSurface(SurfaceBase):
    def __init__(
        self,
        zs: np.ndarray,
        centre: np.ndarray,
        radius_grid: np.ndarray,
        rim: np.ndarray,
        angles: np.ndarray,
    ) -> None:
        self.zs = np.asarray(zs, dtype=float)
        self.centre_xy = np.asarray(centre, dtype=float)
        self.bottom_z = float(self.zs[0])
        self._angles = np.asarray(angles, dtype=float)

        theta = np.concatenate(
            [self._angles[-PAD:] - TWO_PI, self._angles, self._angles[:PAD] + TWO_PI]
        )
        grid = np.concatenate(
            [radius_grid[:, -PAD:], radius_grid, radius_grid[:, :PAD]], axis=1
        )
        self._radial = RectBivariateSpline(self.zs, theta, grid, kx=3, ky=3)
        self._rim = np.concatenate([rim[-PAD:], rim, rim[:PAD]])
        self._rim_theta = theta
        self.length = float(np.mean(rim) - self.bottom_z)
        self._min_curvature: float | None = None

        # Mean and extreme radius per v, for the Mercator domain and for the
        # callers that only want a size.  Sampled rather than derived: v is a
        # different slice of the leg in every column.
        probe_u = np.linspace(0.0, 1.0, 96, endpoint=False)
        probe_v = np.linspace(0.0, 1.0, 96)
        uu, vv = np.meshgrid(probe_u, probe_v)
        p = self.point(uu, vv)
        rho = np.linalg.norm(p[..., :2] - self._centre_of(p[..., 2]), axis=-1)
        self._v_table = probe_v
        self._mean = rho.mean(axis=1)
        self._lo = rho.min(axis=1)
        self._hi = rho.max(axis=1)

    # --- coordinates -------------------------------------------------------

    def rim_at(self, theta: np.ndarray) -> np.ndarray:
        """Height of the rim at a section angle."""
        return np.interp(
            np.asarray(theta, dtype=float), self._rim_theta, self._rim, period=TWO_PI
        )

    def _centre_of(self, z: np.ndarray) -> np.ndarray:
        z = np.clip(np.asarray(z, dtype=float), self.zs[0], self.zs[-1])
        return np.stack(
            [np.interp(z, self.zs, self.centre_xy[:, i]) for i in range(2)], axis=-1
        )

    def radial(self, theta: np.ndarray, z: np.ndarray) -> np.ndarray:
        theta = np.asarray(theta, dtype=float)
        theta = ((theta + np.pi) % TWO_PI) - np.pi
        z = np.clip(np.asarray(z, dtype=float), self.zs[0], self.zs[-1])
        theta, z = np.broadcast_arrays(theta, z)
        return self._radial.ev(z.ravel(), theta.ravel()).reshape(theta.shape)

    # --- SurfaceBase -------------------------------------------------------

    def point(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        u, v = np.broadcast_arrays(u, v)
        theta = TWO_PI * (u % 1.0)
        z = self.bottom_z + np.clip(v, 0.0, 1.0) * (self.rim_at(theta) - self.bottom_z)
        r = self.radial(theta, z)
        c = self._centre_of(z)
        return np.stack(
            [c[..., 0] + r * np.cos(theta), c[..., 1] + r * np.sin(theta), z], axis=-1
        )

    def inner_grid(self, outer: np.ndarray, thickness: float) -> np.ndarray:
        """The inside of the wall: straight in along each section's radius.

        Keeps every vertex at its own angle and its own height, so the two
        skins meet exactly on the rim.  The leg tapers gently enough that the
        wall loses under two per cent of its thickness by going radially
        rather than along the true normal.
        """
        centre = self._centre_of(outer[..., 2])
        offset = outer[..., :2] - centre
        length = np.linalg.norm(offset, axis=-1, keepdims=True)
        direction = offset / np.maximum(length, 1e-9)
        inner = outer.copy()
        inner[..., :2] = centre + direction * np.maximum(length - thickness, 0.1)
        return inner

    def radius(self, v: np.ndarray) -> np.ndarray:
        return np.interp(np.clip(np.asarray(v, dtype=float), 0.0, 1.0), self._v_table, self._mean)

    def semi_axes(self, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        v = np.clip(np.atleast_1d(np.asarray(v, dtype=float)), 0.0, 1.0)
        return np.interp(v, self._v_table, self._lo), np.interp(v, self._v_table, self._hi)

    def min_curvature_radius(self, rows: int = 120, around: int = 360) -> float:
        """Tightest outward bulge, which is the ceiling on wall thickness.

        Measured on rings of constant HEIGHT, not of constant v.  A v-line on
        this surface is tilted wherever the rim dips, so reading curvature
        along one would read the slope of the notch as a bend in the skin and
        cap the wall at a few millimetres.  The rim is a boundary; it curves
        nothing.  Only convex stretches count, since a hollow folds no offset.

        The three points are taken CURVATURE_BASELINE apart rather than
        neighbour to neighbour: the section shape comes from a subdivided mesh
        and every facet corner on it is a kink a millimetre across, which
        nothing the cover does happens on the scale of.
        """
        if self._min_curvature is not None:
            return self._min_curvature
        base = CURVATURE_BASELINE
        theta = np.linspace(-np.pi, np.pi, around, endpoint=False)
        z = np.linspace(self.zs[0], self.zs[-1], rows)
        tt, zz = np.meshgrid(theta, z)
        r = self.radial(tt, zz)
        xy = np.stack([r * np.cos(tt), r * np.sin(tt)], axis=-1)

        spacing = np.linalg.norm(np.roll(xy, -1, axis=1) - xy, axis=-1).mean(axis=1)
        k_section = max(1, int(round(base / max(spacing.mean(), 1e-6))))
        d1 = (np.roll(xy, -k_section, axis=1) - np.roll(xy, k_section, axis=1)) / 2.0
        d2 = np.roll(xy, -k_section, axis=1) - 2.0 * xy + np.roll(xy, k_section, axis=1)
        cross = d1[..., 0] * d2[..., 1] - d1[..., 1] * d2[..., 0]
        speed = np.linalg.norm(d1, axis=-1)
        # Convex outward only: the sign of the turn says which way it bends.
        kappa = np.where(cross < -1e-12, np.abs(cross) / np.maximum(speed**3, 1e-12), 0.0)
        r_section = float(1.0 / max(np.max(kappa), 1e-9))

        step = max(1, int(round(base / ((self.zs[-1] - self.zs[0]) / (rows - 1)))))
        rho = r
        g2 = rho[: -2 * step] - 2.0 * rho[step:-step] + rho[2 * step :]
        g1 = (rho[2 * step :] - rho[: -2 * step]) / 2.0
        dz = (z[1] - z[0]) * step
        g2 = g2 / dz**2
        g1 = g1 / dz
        convex = g2 < -1e-9
        r_meridian = (
            float(1.0 / max(np.max(np.abs(g2[convex]) / (1.0 + g1[convex] ** 2) ** 1.5), 1e-9))
            if np.any(convex)
            else np.inf
        )
        self._min_curvature = min(r_section, r_meridian)
        return self._min_curvature
