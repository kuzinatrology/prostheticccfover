"""Leaves on the back of the anatomic cover.

Nothing about leaves is written here. `transfemoral/leaves.py` already draws
one and already knows how to lay rows of them down the back midline, shrink
them until they fit and drop the row that will not; all of that is used as it
stands.

What it wants is a layout — the transfemoral cover's object, which knows about
seams, clamp shelves and two halves. This cover has none of those: it is one
skin whose only edges are the rim and the bottom. So this is the adapter that
answers the three questions `place` actually asks a layout, and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .surface import SurfaceBase
from .transfemoral.leaves import BACK_MIDLINE_U, LeafSpec, place as _place

CLEAR_MARGIN = 0.035
"""How much (u, v) around the leaves is cleared of cells, so the drawing has
ground to read against. Cells packed up against a leaf turn it into noise —
this is the same trade the transfemoral cover makes by handing the leaves its
whole back half."""

BACK_SECTOR = 0.22
"""How much of the way round counts as the back, either side of the midline."""


class _Column:
    """A surface that can answer in heights, which is how `place` measures.

    On this cover v is not a height: every column of the unwrapping ends on
    the rim, so v = 1 is a different z at every angle. Leaves only ever go
    down the back midline, so that one column is the mapping `place` needs.
    """

    def __init__(self, surface: SurfaceBase, u: float, samples: int = 400) -> None:
        self.surface = surface
        self._v = np.linspace(0.0, 1.0, samples)
        self._z = surface.point(np.full_like(self._v, u), self._v)[:, 2]

    def z_of_v(self, v):
        return np.interp(np.asarray(v, dtype=float), self._v, self._z)

    def v_of_z(self, z):
        return np.interp(np.asarray(z, dtype=float), self._z, self._v)

    def point(self, u, v):
        return self.surface.point(u, v)


@dataclass
class _Layout:
    """The three things `place` asks of a layout, and no more."""

    surface: _Column

    def uv_mm(self, u: float, v: float) -> tuple[float, float]:
        """Millimetres per unit u and per unit v at a point."""
        e = 1e-4
        p0 = self.surface.point(u, v)
        pu = self.surface.point(u + e, v)
        pv = self.surface.point(u, min(v + e, 1.0))
        return float(np.linalg.norm(pu - p0) / e), float(np.linalg.norm(pv - p0) / e)


def _fields(surface: SurfaceBase, column: _Column, keep_extra=None, keep_at=None):
    """`keep_at`: room to the nearest edge, in mm. `back_at`: the back sector.

    The rim is the only edge overhead and the bottom the only one below, so
    room is the shorter run up or down that column — a truer answer than a
    fixed margin, because the rim dips.

    Tabulated over the whole unwrapping once: the fitting test reads it a few
    thousand times per candidate leaf, and walking the surface for each read
    costs more than the search it serves.
    """
    us = np.linspace(0.0, 1.0, 96, endpoint=False)
    vs = np.linspace(0.0, 1.0, 96)
    uu, vv = np.meshgrid(us, vs, indexing="ij")
    p = surface.point(uu, vv)
    step = np.linalg.norm(np.diff(p, axis=1), axis=2)
    run = np.concatenate([np.zeros((len(us), 1)), np.cumsum(step, axis=1)], axis=1)
    room = np.minimum(run, run[:, -1:] - run)

    if keep_at is not None:
        # A caller with a real distance-to-every-edge field hands it over and
        # the run along the column is not used at all.  The run is a fallback:
        # it only knows the rim above and the rim below, so on a cover with a
        # notch or a seam it reports room that is not there, and on one
        # without it reports less room than there is.
        room = np.asarray(keep_at(uu, vv), dtype=float)
    if keep_extra is not None:
        # Any other edge the caller knows about -- on the fastened cover the
        # notch, which opens exactly where the leaves want to go.
        room = np.minimum(room, np.asarray(keep_extra(uu, vv), dtype=float))

    def keep_at(u, v):
        u = np.asarray(u, dtype=float) % 1.0
        v = np.clip(np.asarray(v, dtype=float), 0.0, 1.0)
        u, v = np.broadcast_arrays(u, v)
        iu = np.clip((u * len(us)).astype(int), 0, len(us) - 1)
        iv = np.clip((v * (len(vs) - 1)).astype(int), 0, len(vs) - 1)
        return room[iu, iv]

    def back_at(u, v):
        u = np.asarray(u, dtype=float)
        du = (u - BACK_MIDLINE_U + 0.5) % 1.0 - 0.5
        return (BACK_SECTOR - np.abs(du)) * 100.0

    return keep_at, back_at


def place(surface: SurfaceBase, spec: LeafSpec, keep_extra=None, keep_at=None):
    """Leaf panels as rings in (u, v), what the fitting cost, and the ground
    the cell field has to leave to them."""
    column = _Column(surface, BACK_MIDLINE_U)
    room_at, back_at = _fields(surface, column, keep_extra, keep_at)
    rings, notes = _place(spec, _Layout(column), room_at, back_at)
    if not rings:
        return rings, notes, None
    us = np.concatenate([r[:, 0] for r in rings])
    vs = np.concatenate([r[:, 1] for r in rings])
    reach = max(abs(us.max() - BACK_MIDLINE_U), abs(BACK_MIDLINE_U - us.min())) + CLEAR_MARGIN
    keepout = (
        BACK_MIDLINE_U - reach,
        BACK_MIDLINE_U + reach,
        float(vs.min()) - CLEAR_MARGIN,
        float(vs.max()) + CLEAR_MARGIN,
    )
    return rings, notes, keepout
