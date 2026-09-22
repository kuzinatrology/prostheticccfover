"""Stock solids built from a cover's own surface.

Both covers that use this store their shape the same way -- an outer radius
over angle and height about a centre line -- so every solid here is a loft of
that, offset radially.  Radially, not along the normal: that is how both covers
build their own inner wall (`anatomic/stage6_shell.py` explains why), and a
land or a web built the other way would not sit on the wall they actually have.
"""

from __future__ import annotations

import numpy as np
import trimesh
from manifold3d import Manifold, OpType

from .. import mesh_build as mb


def centre_of(surface, z: np.ndarray) -> np.ndarray:
    """The cover's centre line at these heights, whatever it calls it."""
    z = np.atleast_1d(np.asarray(z, dtype=float))
    fn = getattr(surface, "centre", None) or getattr(surface, "_centre_of")
    return np.atleast_2d(fn(z))


def inset(surface, grid: np.ndarray, distance) -> np.ndarray:
    """Pull a grid of surface points `distance` mm toward the centre line.

    Each cover already knows how to do this -- it is how both build their own
    inner wall -- so use the cover's own method where there is one and keep the
    wall the fasteners sit on identical to the wall the cover was made with.
    """
    if np.isscalar(distance) and distance == 0.0:
        return grid
    if not np.isscalar(distance):
        # A depth that changes with height, which is how a land is built: deep
        # where the prosthesis leaves room and shallow where it does not.  The
        # covers' own offsets take one number, so this goes radially -- which
        # loses a little depth where the wall leans, and losing depth is the
        # safe direction for a part that must not touch the prosthesis.
        d = np.asarray(distance, dtype=float)
        if d.ndim == 1:
            d = d[:, None]
        c = centre_of(surface, grid[..., 2].ravel()).reshape(grid.shape[:-1] + (2,))
        off = grid[..., :2] - c
        n = np.linalg.norm(off, axis=-1, keepdims=True)
        out = grid.copy()
        out[..., :2] = c + off / np.maximum(n, 1e-9) * np.maximum(n - d[..., None], 0.1)
        return out
    for name in ("inner_grid", "offset_grid"):
        fn = getattr(surface, name, None)
        if fn is None:
            continue
        try:
            return fn(grid, distance)
        except (ValueError, IndexError):
            # The Rhino cover's own offset wants a grid on its stored 360
            # columns; on any other width it declines, and the radial offset
            # below is what it would have done anyway.
            break
    c = centre_of(surface, grid[..., 2].ravel()).reshape(grid.shape[:-1] + (2,))
    d = grid[..., :2] - c
    n = np.linalg.norm(d, axis=-1, keepdims=True)
    out = grid.copy()
    out[..., :2] = c + d / np.maximum(n, 1e-9) * np.maximum(n - distance, 0.1)
    return out


def columns_for(surface, cols: int | None) -> int:
    """How many columns a grid for this cover wants.

    The Rhino cover offsets a grid only on the 360 columns it is stored on, and
    its own offset leans with the wall where a plain radial one does not -- on
    that cover the difference is a seventh of the wall's volume.  So ask the
    cover first and only then fall back to the caller's number.
    """
    stored = getattr(getattr(surface, "data", None), "theta", None)
    if stored is not None:
        return len(stored)
    return cols or 360


def loft(surface, distance, rows: int = 240, cols: int | None = None,
         v_range: tuple[float, float] = (0.0, 1.0)) -> np.ndarray:
    """Grid over the cover's own (u, v) square, pulled in by `distance`.

    Over (u, v) and not over (angle, height) because on the anatomic cover the
    rim is a curve: every column of the (u, v) grid ends on its own point of
    it, and a rectangular grid of heights would run out over the top.
    """
    cols = columns_for(surface, cols)
    u = np.linspace(0.0, 1.0, cols, endpoint=False)
    v = np.linspace(v_range[0], v_range[1], rows)
    uu, vv = np.meshgrid(u, v)
    return inset(surface, surface.point(uu, vv), distance)


def _loft_faces(rows: int, cols: int) -> np.ndarray:
    index = np.arange(rows * cols).reshape(rows, cols)
    right = (np.arange(cols) + 1) % cols
    a, b = index[:-1, :], index[:-1, right]
    c, d = index[1:, right], index[1:, :]
    return np.concatenate([
        np.stack([a, b, c], -1).reshape(-1, 3),
        np.stack([a, c, d], -1).reshape(-1, 3),
    ])


def band(surface, outer, inner, rows: int = 240, cols: int | None = None,
         v_range: tuple[float, float] = (0.0, 1.0)) -> Manifold:
    """A closed solid between two radial offsets, capped top and bottom.

    `outer` and `inner` are insets from the outer skin, so (0, wall) is the
    cover's own wall and (0, wall + land) is the wall with room for a land
    under it.
    """
    out = loft(surface, outer, rows, cols, v_range)
    inn = loft(surface, inner, rows, cols, v_range)
    r, c, _ = out.shape
    faces = _loft_faces(r, c)
    verts = np.vstack([out.reshape(-1, 3), inn.reshape(-1, 3)])
    n = r * c
    index = np.arange(n).reshape(r, c)
    right = (np.arange(c) + 1) % c

    def cap(ring: np.ndarray, flip: bool) -> np.ndarray:
        a, b = ring, ring[right]
        quads = np.concatenate([
            np.stack([a, b, b + n], -1),
            np.stack([a, b + n, a + n], -1),
        ])
        return quads[:, ::-1] if flip else quads

    mesh = trimesh.Trimesh(
        vertices=verts,
        faces=np.vstack([
            faces,                      # outer skin
            faces[:, ::-1] + n,         # inner skin, wound the other way
            cap(index[0], True),
            cap(index[-1], False),
        ]),
        process=False,
    )
    trimesh.repair.fix_normals(mesh)
    return mb.to_manifold(mesh)


def core(surface, wall: float, rows: int = 240, cols: int | None = None) -> Manifold:
    """The volume the cover encloses: its inner skin, capped at both ends.

    What a web is cut out of -- a web has to reach the wall and stop there, and
    this is the shape that says where "there" is at every angle and height.
    """
    grid = loft(surface, wall, rows, cols)
    r, c, _ = grid.shape
    n = r * c
    index = np.arange(n).reshape(r, c)
    right = (np.arange(c) + 1) % c
    verts = np.vstack([grid.reshape(-1, 3), grid[-1].mean(axis=0), grid[0].mean(axis=0)])
    top_hub, bottom_hub = n, n + 1
    faces = np.vstack([
        _loft_faces(r, c),
        np.stack([index[-1], index[-1][right], np.full(c, top_hub)], -1),
        np.stack([index[0], index[0][right], np.full(c, bottom_hub)], -1)[:, ::-1],
    ])
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    trimesh.repair.fix_normals(mesh)
    return mb.to_manifold(mesh)


def slab(centre: np.ndarray, normal: str, half: float, size: float = 900.0) -> Manifold:
    """An infinite-ish slab of half-thickness `half` about a plane."""
    axis = {"x": 0, "y": 1, "z": 2}[normal]
    dims = [size, size, size]
    dims[axis] = 2.0 * half
    box = Manifold.cube(dims, center=True)
    return box.translate(list(np.asarray(centre, dtype=float)))


def add(parts: list[Manifold]) -> Manifold:
    parts = [p for p in parts if p is not None]
    return parts[0] if len(parts) == 1 else Manifold.batch_boolean(parts, OpType.Add)


def sub(body: Manifold, parts: list[Manifold]) -> Manifold:
    parts = [p for p in parts if p is not None]
    return body if not parts else Manifold.batch_boolean([body, *parts], OpType.Subtract)
