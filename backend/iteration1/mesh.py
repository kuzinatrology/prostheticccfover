"""Closing the modelled skin into a solid.

The Rhino file is already a solid, but its wall is fixed and its mesh is a
loft of long thin rows with a tangle in it.  Rebuilding the cover from the
grid measured off it gives back the same shape as a clean manifold, with the
wall as a slider and with the rims exactly on the two rim curves — which is
what the pattern needs, because a boolean against a mesh that is not closed
does not have an answer.
"""

from __future__ import annotations

import numpy as np
import trimesh


def loft_faces(rows: int, cols: int) -> np.ndarray:
    """Triangles of an open tube over a (rows, cols) grid, wrapping in u."""
    index = np.arange(rows * cols).reshape(rows, cols)
    right = (np.arange(cols) + 1) % cols
    a, b = index[:-1, :], index[:-1, right]
    c, d = index[1:, right], index[1:, :]
    return np.concatenate(
        [np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)]
    )


def shell(outer: np.ndarray, inner: np.ndarray) -> trimesh.Trimesh:
    """Outer skin, inner skin, and a band closing each rim.

    Both grids share the parameterisation, so the two rims close row by row
    and the result is one closed manifold: a tube with a wall, which is what a
    cover is.
    """
    rows, cols, _ = outer.shape
    faces = loft_faces(rows, cols)
    top = outer.reshape(-1, 3)
    bottom = inner.reshape(-1, 3)
    offset = len(top)
    index = np.arange(rows * cols).reshape(rows, cols)
    right = (np.arange(cols) + 1) % cols

    def band(ring_a: np.ndarray, ring_b: np.ndarray) -> np.ndarray:
        return np.concatenate(
            [
                np.stack([ring_a, ring_a[right], ring_b[right]], -1),
                np.stack([ring_a, ring_b[right], ring_b], -1),
            ]
        )

    all_faces = np.vstack(
        [
            faces,
            faces[:, ::-1] + offset,
            band(index[-1], index[-1] + offset),  # the top rim
            band(index[0] + offset, index[0]),    # the bottom rim
        ]
    )
    mesh = trimesh.Trimesh(np.vstack([top, bottom]), all_faces, process=True)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    if mesh.volume < 0:
        mesh.invert()
    return mesh
