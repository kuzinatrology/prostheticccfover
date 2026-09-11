"""A picture, turned into the shape of a hole.

The cell field still decides *where* the holes are and *how big*. This module
answers only one question: what shape. An image comes in, a polygon in the
unit square comes out, and `pattern.py` fits it into every cell it has
already sized.

Three things happen on the way, in this order:

  1. a binary mask, from the alpha channel where there is one and from Otsu's
     threshold where there is not;
  2. contours, by marching squares, nested into outlines and their holes,
     simplified, and trimmed to the twelve largest;
  3. normalisation into the unit square, so nothing downstream knows how big
     the picture was.

The result is cached on the file's digest together with the three controls
that change it, so dragging any other slider never re-reads the picture.

Interior openings are filled for `solid`. A hole inside a hole is a disc of
shell with nothing holding it: it would drop out of the print. `shape` keeps
them, because that is what the picture said, and the tests read it.
"""

from __future__ import annotations

import hashlib
import io
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

MAX_BYTES = 8 * 1024 * 1024
"""Largest upload accepted, in bytes."""

MAX_SIDE = 4000
"""Largest image accepted, per side, in pixels."""

WORK_SIDE = 512
"""Long side the picture is reduced to before anything is measured.

Marching squares on 512 pixels already resolves more detail than a hole three
centimetres across can carry, and it costs nothing to trace.
"""

MAX_SHAPES = 12
"""Outlines kept. Past this a picture is noise, not a motif."""

MIN_SHARE = 0.01
"""An outline smaller than this share of the largest one is dust."""

SMOOTH_LO, SMOOTH_HI = 0.002, 0.02
"""Simplification tolerance at either end of `motif_smoothing`, as a fraction
of the picture's long side."""

MAX_CONTOURS = 400
"""Contours carried into the nesting pass. A photograph under a badly placed
threshold can produce thousands, and all but the largest are speckle."""

LIBRARY_SIZE = 8
"""Uploads held at once. Nothing is written to disk."""

# Pillow will not open an image that claims more pixels than this, which is
# what stops a small file from expanding into a large allocation.
Image.MAX_IMAGE_PIXELS = MAX_SIDE * MAX_SIDE


class MotifError(ValueError):
    """The bytes are not a picture this can read. The only refusal here."""


@dataclass(frozen=True)
class Motif:
    """One picture, vectorised.

    `shape` is what the picture said; `solid` is what can be cut. They differ
    only by the interior openings, which are filled in `solid` because nothing
    would hold them. Both live in the unit square: bounding box centred on the
    origin, longer side exactly one, y pointing up.
    """

    shape: MultiPolygon
    solid: MultiPolygon
    digest: str
    found: int
    """Outlines the picture had, before the twelve-largest trim."""
    filled: int
    """Interior openings that were filled."""

    @property
    def is_empty(self) -> bool:
        return self.solid.is_empty

    @property
    def notes(self) -> list[str]:
        out: list[str] = []
        if self.found > len(self.solid.geoms):
            out.append(f"Using {len(self.solid.geoms)} largest shapes of {self.found}")
        if self.filled:
            out.append("Inner openings filled, nothing would hold them")
        return out

    def paths(self) -> list[str]:
        """The outlines as SVG path data, for the silhouette preview."""
        return [_path_d(poly) for poly in self.solid.geoms]


EMPTY = Motif(MultiPolygon(), MultiPolygon(), "", 0, 0)


# --- the picture --------------------------------------------------------


def _decode(data: bytes) -> Image.Image:
    """Bytes to a picture, by content rather than by what the upload claimed.

    An SVG is rasterised at the working size rather than read as paths. It is
    the same marching-squares path as everything else, and one code path is
    worth more here than the last half pixel of fidelity.
    """
    if len(data) > MAX_BYTES:
        raise MotifError("file is larger than 8 MB")
    head = data[:512].lstrip()
    if head.startswith((b"<?xml", b"<svg")) or b"<svg" in head:
        try:
            import cairosvg

            png = cairosvg.svg2png(
                bytestring=data, output_width=WORK_SIDE, output_height=WORK_SIDE
            )
        except MotifError:
            raise
        except Exception as exc:  # any parse failure is the same answer
            raise MotifError("this SVG could not be read") from exc
        data = png
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except MotifError:
        raise
    except Exception as exc:
        raise MotifError("this file is not a picture") from exc
    if img.width > MAX_SIDE or img.height > MAX_SIDE:
        raise MotifError(f"picture is larger than {MAX_SIDE} by {MAX_SIDE}")
    return img


def _sample(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Luminance and alpha, both in [0, 1], reduced to the working size."""
    img = _decode(data)
    img.thumbnail((WORK_SIDE, WORK_SIDE), Image.LANCZOS)
    arr = np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0
    grey = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    return grey, arr[..., 3]


def binary_mask(
    grey: np.ndarray, alpha: np.ndarray, bias: float, invert: bool
) -> np.ndarray:
    """Where the figure is.

    Alpha first: a cut-out leaf carries its own silhouette and no threshold
    can beat it. Otherwise Otsu's method splits the histogram where the two
    clusters of brightness part company, and `bias` slides that split, because
    on a photograph the automatic answer is often a little off and this is the
    only way to let somebody put it right.

    Which side of the split is the figure is decided by the border: whatever
    runs around the edge of the picture is the background.
    """
    from skimage.filters import threshold_otsu

    if float(alpha.min()) < 1.0 - 1e-6:
        level = float(np.clip(0.5 - bias, 0.02, 0.98))
        mask = alpha >= level
    elif float(grey.max() - grey.min()) < 1e-6:
        mask = np.zeros(grey.shape, dtype=bool)
    else:
        level = float(np.clip(threshold_otsu(grey) + bias, 0.0, 1.0))
        mask = grey >= level

    border = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]])
    if border.mean() > 0.5:
        mask = ~mask
    return ~mask if invert else mask


# --- contours -----------------------------------------------------------


def _rings(mask: np.ndarray) -> list[Polygon]:
    """Marching squares, at the half-way level, in (x, y) with y up.

    The mask is padded with a ring of background so a figure that runs off the
    edge of the picture still closes into a loop.
    """
    from skimage.measure import find_contours

    padded = np.pad(mask, 1, constant_values=False).astype(float)
    out: list[Polygon] = []
    for contour in find_contours(padded, 0.5):
        if len(contour) < 4:
            continue
        ring = np.stack([contour[:, 1], -contour[:, 0]], axis=1)
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
        out.extend(_polygons(poly))
    out.sort(key=lambda p: p.area, reverse=True)
    return out[:MAX_CONTOURS]


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    """Every polygon in a geometry, however it came out of `buffer(0)`."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area > 0 else []
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _polygons(g)]
    return []


def _nest(rings: list[Polygon]) -> list[Polygon]:
    """Outlines with their holes.

    Marching squares traces the edge of a hole as readily as the edge of a
    figure, and hands both back as plain loops. A loop lying inside exactly
    one other is that one's hole. A loop inside two is an island in a hole and
    is dropped: the hole is filled before anything is cut, so the island has
    nowhere to be.

    Nesting is decided by a single point on each loop rather than by the loop
    as a whole. Contours from marching squares never cross and never touch, so
    one point settles it, and the tree keeps the comparison off every pair.
    """
    from shapely import STRtree
    from shapely.geometry import Point

    probes = [Point(p.exterior.coords[0]) for p in rings]
    tree = STRtree(rings)
    inside: list[list[int]] = []
    for i, probe in enumerate(probes):
        inside.append(
            [int(j) for j in tree.query(probe) if j != i and rings[j].contains(probe)]
        )

    out: list[Polygon] = []
    for i, ring in enumerate(rings):
        if inside[i]:
            continue
        holes = [
            rings[j].exterior.coords
            for j in range(len(rings))
            if inside[j] == [i]
        ]
        poly = Polygon(ring.exterior.coords, holes)
        if not poly.is_valid:
            poly = poly.buffer(0)
        out.extend(_polygons(poly))
    return out


def _simplify(polys: list[Polygon], smoothing: float, size: float) -> list[Polygon]:
    """Take the pixel staircase off the edges."""
    tolerance = (SMOOTH_LO + (SMOOTH_HI - SMOOTH_LO) * smoothing) * size
    out: list[Polygon] = []
    for poly in polys:
        simple = poly.simplify(tolerance)
        if not simple.is_valid:
            simple = simple.buffer(0)
        out.extend(p for p in _polygons(simple) if p.area > 0)
    return out


def _normalise(polys: list[Polygon]) -> list[Polygon]:
    """Into the unit square: bounding box centred, longer side exactly one."""
    if not polys:
        return []
    x0, y0, x1, y1 = unary_union(polys).bounds
    span = max(x1 - x0, y1 - y0)
    if span <= 0:
        return []
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    k = 1.0 / span

    def move(poly: Polygon) -> Polygon:
        def ring(coords):
            a = np.asarray(coords, dtype=float)
            return np.stack([(a[:, 0] - cx) * k, (a[:, 1] - cy) * k], axis=1)

        return Polygon(ring(poly.exterior.coords), [ring(h.coords) for h in poly.interiors])

    return [move(p) for p in polys]


# --- the whole way through ----------------------------------------------


def vectorise(data: bytes, *, threshold_bias: float, invert: bool, smoothing: float) -> Motif:
    """A picture to a motif. Raises `MotifError` only when the bytes are not one."""
    grey, alpha = _sample(data)
    mask = binary_mask(grey, alpha, threshold_bias, invert)
    digest = hashlib.sha256(data).hexdigest()[:16]
    if not mask.any():
        return Motif(MultiPolygon(), MultiPolygon(), digest, 0, 0)

    polys = _nest(_rings(mask))
    polys = _simplify(polys, smoothing, float(max(mask.shape)))
    if not polys:
        return Motif(MultiPolygon(), MultiPolygon(), digest, 0, 0)

    largest = max(p.area for p in polys)
    polys = [p for p in polys if p.area >= MIN_SHARE * largest]
    found = len(polys)
    polys.sort(key=lambda p: p.area, reverse=True)
    polys = _normalise(polys[:MAX_SHAPES])

    filled = sum(len(p.interiors) for p in polys)
    solid = [Polygon(p.exterior.coords) for p in polys]
    return Motif(MultiPolygon(polys), MultiPolygon(solid), digest, found, filled)


def _path_d(poly: Polygon) -> str:
    """One outline as SVG path data, three decimals of the unit square."""
    parts = []
    for ring in [poly.exterior, *poly.interiors]:
        pts = np.asarray(ring.coords, dtype=float)[:-1]
        if len(pts) < 3:
            continue
        head = f"M{pts[0, 0]:.3f} {pts[0, 1]:.3f}"
        body = "".join(f"L{x:.3f} {y:.3f}" for x, y in pts[1:])
        parts.append(head + body + "Z")
    return "".join(parts)


# --- what the session is holding ----------------------------------------


class Library:
    """Uploaded pictures, in memory, for the life of the process.

    Nothing is written to disk and nothing is kept beyond the last few
    uploads, so an image the user is done with leaves on its own.
    """

    def __init__(self, limit: int = LIBRARY_SIZE):
        self.limit = limit
        self._held: OrderedDict[str, bytes] = OrderedDict()

    def add(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()[:16]
        self._held[digest] = data
        self._held.move_to_end(digest)
        while len(self._held) > self.limit:
            self._held.popitem(last=False)
        return digest

    def get(self, digest: str) -> bytes | None:
        data = self._held.get(digest)
        if data is not None:
            self._held.move_to_end(digest)
        return data

    def clear(self) -> None:
        self._held.clear()


LIBRARY = Library()


@lru_cache(maxsize=32)
def _cached(digest: str, bias: float, invert: bool, smoothing: float) -> Motif:
    data = LIBRARY.get(digest)
    if data is None:
        return EMPTY
    return vectorise(data, threshold_bias=bias, invert=invert, smoothing=smoothing)


def held(digest: str, bias: float, invert: bool, smoothing: float) -> Motif:
    """The motif for an upload already in the library, cached on its controls.

    Rounding the two continuous controls to their own slider step is what
    keeps a drag from re-tracing the picture at every intermediate value.
    """
    if not digest:
        return EMPTY
    return _cached(digest, round(float(bias), 3), bool(invert), round(float(smoothing), 3))


def resolve(params) -> Motif | None:
    """The motif a parameter set asks for, or None when it asks for cells.

    None and an empty motif are different answers. None means there is no
    picture at all, which is what a design opened after the session that
    uploaded it looks like, and the cover falls back to cells. An empty motif
    means the picture is being held and there was nothing in it, and the cover
    comes out solid.
    """
    if getattr(params, "hole_shape", "cells") != "image":
        return None
    if not params.motif_id or LIBRARY.get(params.motif_id) is None:
        return None
    return held(
        params.motif_id,
        params.threshold_bias,
        params.motif_invert,
        params.motif_smoothing,
    )


__all__ = [
    "LIBRARY",
    "MAX_BYTES",
    "Library",
    "Motif",
    "MotifError",
    "binary_mask",
    "held",
    "resolve",
    "vectorise",
]
