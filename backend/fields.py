"""Scalar fields over the surface's (u, v) square.

Every field is the same kind of thing: a function of (u, v) returning a number
in [0, 1]. Density says how fine the pattern is; mask says how strongly it
shows up at all. The generator never sees anything but these functions, so a
stress field from an FE run or a mask painted in the interface would drop in
without touching the geometry code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

Field = Callable[[float, float], float]


def _smoothstep(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def as_array_field(field: Field) -> Field:
    """Accept either a vectorised or a scalar field function."""

    def wrapped(u, v):
        u_arr = np.asarray(u, dtype=float)
        v_arr = np.asarray(v, dtype=float)
        try:
            out = np.asarray(field(u_arr, v_arr), dtype=float)
            if out.shape == np.broadcast_shapes(u_arr.shape, v_arr.shape):
                return np.clip(out, 0.0, 1.0)
        except Exception:
            pass
        fu, fv = np.broadcast_arrays(u_arr, v_arr)
        out = np.array(
            [float(field(float(a), float(b))) for a, b in zip(fu.ravel(), fv.ravel())]
        ).reshape(fu.shape)
        return np.clip(out, 0.0, 1.0)

    return wrapped


# --- density ------------------------------------------------------------


def constant_density(level: float) -> Field:
    def density(u, v):
        return np.full_like(np.asarray(v, dtype=float), level)

    return density


def graded_density(level: float, gradient: float) -> Field:
    """Denser toward one end. Still just a function of (u, v)."""

    def density(u, v):
        v = np.asarray(v, dtype=float)
        return np.clip(level + gradient * (v - 0.5), 0.0, 1.0)

    return density


# --- mask ---------------------------------------------------------------

MASK_MODES = ("full", "band", "panel", "stripes")


def _height_window(v: np.ndarray, lo: float, hi: float, feather: float) -> np.ndarray:
    # The feather softens the edges of the window; it never eats the middle,
    # so a band always reaches full strength somewhere inside itself.
    f = max(min(feather, (hi - lo) / 2.0), 1e-4)
    return _smoothstep((v - lo) / f) * _smoothstep((hi - v) / f)


def _ring_window(u: np.ndarray, centre: float, width: float, feather: float) -> np.ndarray:
    """A window around the circumference, wrapping at the seam."""
    d = np.abs((np.asarray(u, dtype=float) - centre + 0.5) % 1.0 - 0.5)
    f = max(min(feather, width / 2.0), 1e-4)
    return _smoothstep((width / 2.0 - d) / f)


def full_mask() -> Field:
    def mask(u, v):
        return np.ones_like(np.asarray(v, dtype=float))

    return mask


def band_mask(v_from: float, v_to: float, feather: float) -> Field:
    def mask(u, v):
        return _height_window(np.asarray(v, dtype=float), v_from, v_to, feather)

    return mask


def panel_mask(
    v_from: float,
    v_to: float,
    centre: float,
    width: float,
    mirror: bool,
    feather: float,
) -> Field:
    """A window of pattern on one side of the cover, optionally on both."""

    def mask(u, v):
        u = np.asarray(u, dtype=float)
        ring = _ring_window(u, centre, width, feather)
        if mirror:
            ring = np.maximum(ring, _ring_window(u, centre + 0.5, width, feather))
        return ring * _height_window(np.asarray(v, dtype=float), v_from, v_to, feather)

    return mask


def stripe_mask(
    v_from: float, v_to: float, pitch: float, feather: float
) -> Field:
    """Bands running up the cover, repeating around it."""
    pitch = max(pitch, 0.02)

    def mask(u, v):
        phase = (np.asarray(u, dtype=float) / pitch) % 1.0
        d = np.abs(phase - 0.5) * pitch
        half = 0.3 * pitch
        ring = _smoothstep((half - d) / max(min(feather * pitch, half), 1e-4))
        return ring * _height_window(np.asarray(v, dtype=float), v_from, v_to, feather)

    return mask


@dataclass(frozen=True)
class Fields:
    """The fields a design is made of. One structure, one place to extend."""

    density: Field
    mask: Field

    @classmethod
    def from_params(cls, p) -> "Fields":
        return cls(density=density_from(p), mask=mask_from(p))


def density_from(p) -> Field:
    return graded_density(p.pattern_density, p.density_gradient)


def mask_from(p) -> Field:
    mode = p.mask_mode if p.mask_mode in MASK_MODES else "full"
    lo, hi = sorted((p.mask_v_from, p.mask_v_to))
    if mode == "full":
        return full_mask()
    if mode == "band":
        return band_mask(lo, hi, p.mask_feather)
    if mode == "panel":
        return panel_mask(lo, hi, p.mask_u_center, p.mask_u_width, p.mask_mirror, p.mask_feather)
    return stripe_mask(lo, hi, p.mask_u_width, p.mask_feather)
