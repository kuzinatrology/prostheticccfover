"""What the two reference renders actually say, read off the pixels.

ref_2 is a straight side view, which makes it worth more than a mood board.
Seen from the side, the top boundary of the silhouette *is* the rim: the
height of the rim at a section angle, plotted against how far forward or back
that angle sits.  So the notch can be measured rather than guessed.

ref_1 is a three-quarter view.  Its outline gives a second girth profile and
its dark interior shows the opening, but the camera angle is unknown, so only
its silhouette is used.

Everything comes back as fractions of the cover's own height and girth, so it
carries over to a cover of any size.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from . import config

BACKGROUND_TOLERANCE = 28

TRIM_LOW, TRIM_HIGH = 0.05, 0.92
"""The run of the silhouette that is girth rather than a turning edge."""

RIM_HARMONICS = 5
"""How many cosine terms the rim curve is fitted with.

A side view resolves the rim badly at the two extremes: near the front and
near the back, tens of degrees of the section crowd into a couple of pixels,
so reading the trace angle by angle turns a rounded notch into a spike. The
depths themselves are measured well — it is only the shape between them that
the projection smears — so the trace is fitted with a handful of harmonics.
That is the same thing as the brief's smooth curve through a few control
points, with the points read off the render instead of placed by eye."""


def _mask(path) -> np.ndarray:
    from PIL import Image

    image = np.asarray(Image.open(path).convert("RGB"), dtype=int)
    corner = image[:8, :8].reshape(-1, 3).mean(axis=0)
    return np.abs(image - corner).max(axis=2) > BACKGROUND_TOLERANCE


@lru_cache(maxsize=1)
def read() -> dict:
    """Rim curve and girth profile, both as fractions of the cover's height."""
    out: dict = {}
    for path in config.REF_IMAGES:
        if not path.exists():
            raise SystemExit(f"{path} is missing; stage 3 cannot read the reference")
        mask = _mask(path)
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        height = rows[-1] - rows[0] + 1
        width = np.array([
            np.ptp(np.flatnonzero(mask[y])) + 1 if mask[y].any() else 0
            for y in range(rows[0], rows[-1] + 1)
        ])
        # t = 0 at the bottom of the cover, 1 at the top, as everywhere else.
        t = 1.0 - np.arange(len(width)) / (len(width) - 1)
        out[path.name] = {
            "t": t[::-1],
            "width": width[::-1] / width.max(),
            "widest_at_t": float(t[int(np.argmax(width))]),
            "height_px": int(height),
            "mask": mask,
            "rows": rows,
            "cols": cols,
        }

    side = out[config.REF_IMAGES[1].name]
    mask, rows, cols = side["mask"], side["rows"], side["cols"]
    top = np.array([np.flatnonzero(mask[:, x])[0] for x in cols])
    # Across the side view, left is the front of the leg and right the back:
    # the rim plunges at one end only, and that end is the notch.
    s = (cols - cols[0]) / (cols[-1] - cols[0])
    if (top[-1] - top.min()) < (top[0] - top.min()):
        s = 1.0 - s
        top = top[::-1]
    sin_theta = 1.0 - 2.0 * s
    dip = (top - top.min()) / side["height_px"]

    return {
        "rim_sin_theta": sin_theta,
        "rim_dip": dip,
        "rim_front_dip": float(dip[0]),
        "rim_back_dip": float(dip[-1]),
        "girth": {k: {"t": v["t"], "width": v["width"], "widest_at_t": v["widest_at_t"]}
                  for k, v in out.items()},
    }


def girth(t: np.ndarray) -> np.ndarray:
    """How full the cover is at each relative height, from the renders.

    The side view measures the leg front to back and the three-quarter view
    measures it closer to side to side, so the mean of the two is a fair stand
    in for the girth the silhouette asks for.  Returned in the same arbitrary
    units as the MakeHuman profile it replaces: only its shape matters, since
    the prosthesis sets the size.
    """
    data = read()["girth"]
    # The last few per cent at either end are the rounded bottom lip and the
    # rim itself, where the silhouette narrows to a point because of how the
    # edge turns, not because the cover is thin there.  Read the profile
    # between them and hold it flat outside.
    inner = np.clip(np.asarray(t, dtype=float), TRIM_LOW, TRIM_HIGH)
    curves = [np.interp(inner, v["t"], v["width"]) for v in data.values()]
    return np.mean(curves, axis=0)


def leg_girth(zs: np.ndarray, bottom_z: float, mh_t: np.ndarray, mh_radius: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Girth up the whole cover, in millimetres.

    The renders draw the whole shank, not just its lower half.  It matters
    which, because the MakeHuman base mesh has no waist under the knee at all:
    measured front to back it is 114 mm at the calf and 120 mm at the knee, so
    a leg copied from it is widest where a leg should be narrowing, and reads
    as a post.  The renders put their widest at 64 per cent of the height and
    come back to 86 per cent of it by the knee, which is what a calf looks
    like.

    So the renders give the shape of the whole run from the bottom of the
    cover to the knee, and MakeHuman gives the size — the two are matched at
    the calf, so the calf keeps a real leg's girth.  Above the knee the
    renders stop and MakeHuman carries on up the thigh, matched in turn at the
    joint.
    """
    anatomical = np.interp(t, mh_t, mh_radius)
    below = zs <= 0.0
    if not below.any():
        return anatomical

    shape = girth(np.linspace(0.0, 1.0, 512))
    place = np.linspace(0.0, 1.0, 512)
    where = np.clip((zs[below] - bottom_z) / (0.0 - bottom_z), 0.0, 1.0)
    drawn = np.interp(where, place, shape)

    # Match at the calf: the render's own widest section is made to weigh what
    # a real calf weighs at this leg's length.
    calf_mm = float(anatomical[below].max())
    out = anatomical.copy()
    out[below] = drawn / max(shape.max(), 1e-9) * calf_mm
    # ...and the thigh above is brought onto the end of it without a step.
    if (~below).any():
        out[~below] = anatomical[~below] * (out[below][-1] / max(anatomical[below][-1], 1e-9))
    return out


def rim_heights(angles: np.ndarray, top_z: float, height_mm: float, deepen: float = 0.0) -> np.ndarray:
    """The reference rim, in millimetres, at each section angle.

    A side view folds the two halves of the leg onto each other, so what comes
    out is the rim as a function of sin(theta) — which is exactly a rim
    symmetric left to right, which this one is.  `deepen` takes the notch
    further down without changing its shape, for when the knee needs more room
    than the reference leaves it.
    """
    angles = np.asarray(angles, dtype=float)
    dip = _fitted_dip()(angles)
    extra = deepen * np.clip(-np.sin(angles), 0.0, 1.0) ** 2
    return top_z - (dip * height_mm + extra)


@lru_cache(maxsize=1)
def _fitted_dip():
    """The measured rim trace as a smooth, left-right symmetric curve."""
    data = read()
    # phi = 0 at the front of the leg, pi at the back. The rim is symmetric
    # about that axis, so it is a cosine series in phi and nothing else.
    phi = np.linspace(0.0, np.pi, 721)
    measured = np.interp(
        np.cos(phi), data["rim_sin_theta"][::-1], data["rim_dip"][::-1]
    )
    basis = np.stack([np.cos(k * phi) for k in range(RIM_HARMONICS + 1)], axis=1)
    coeffs, *_ = np.linalg.lstsq(basis, measured, rcond=None)

    def dip(angles: np.ndarray) -> np.ndarray:
        # theta = pi/2 is the front, so phi = |theta - pi/2| folded to [0, pi].
        p = np.abs(((np.asarray(angles) - np.pi / 2) + np.pi) % (2 * np.pi) - np.pi)
        return np.clip(
            sum(c * np.cos(k * p) for k, c in enumerate(coeffs)), 0.0, None
        )

    return dip
