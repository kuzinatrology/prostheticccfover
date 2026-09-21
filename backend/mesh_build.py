"""From the parameter square to a closed, printable solid.

The shell is built as two offset copies of the same (u, v) grid, stitched at
the two rims. The holes are built as prisms driven straight through the wall
and removed with one boolean. Nothing here decides what is printable; it only
builds what `pattern` has already made safe.
"""

from __future__ import annotations

import numpy as np
import trimesh
from manifold3d import Manifold, Mesh, OpType
from shapely import constrained_delaunay_triangles, get_coordinates, get_num_geometries
from shapely.geometry import Polygon

from .surface import Surface

WALL_OVERSHOOT = 0.6
"""mm the cutting prisms stick out past each wall face."""

SAGITTA_MARGIN = 1.5
"""Safety factor on the bulge allowance for a prism's flat end caps."""


def _flip_if_inverted(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Make the winding enclose a positive volume."""
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    return faces[:, ::-1] if mesh.volume < 0 else faces


def shell(surface: Surface, thickness: float, nu: int, nv: int) -> trimesh.Trimesh:
    """Closed tube of constant wall thickness, open at neither end (a solid)."""
    outer, normal = surface.grid(nu, nv)
    return shell_from(outer, outer - normal * thickness)


def shell_from(outer: np.ndarray, inner: np.ndarray) -> trimesh.Trimesh:
    """Close a solid between two (nv, nu, 3) grids sharing a parameterisation.

    Relief is nothing more than a displaced outer grid handed to this, which
    is why raising or sinking a pattern needs no boolean at all.
    """
    nv, nu = outer.shape[:2]
    n = nu * nv
    vertices = np.vstack([outer.reshape(-1, 3), inner.reshape(-1, 3)])

    j, i = np.meshgrid(np.arange(nv - 1), np.arange(nu), indexing="ij")
    j, i = j.ravel(), i.ravel()
    i1 = (i + 1) % nu
    o00, o01 = j * nu + i, j * nu + i1
    o11, o10 = (j + 1) * nu + i1, (j + 1) * nu + i

    # Walking +u then +v is counter-clockwise in the parameter square, so this
    # winding matches the outward normal.
    outer_faces = np.vstack([np.stack([o00, o01, o11], 1), np.stack([o00, o11, o10], 1)])
    inner_faces = outer_faces[:, ::-1] + n

    # Rims: an annulus at each open end, closing the solid.
    i = np.arange(nu)
    i1 = (i + 1) % nu
    bottom = np.vstack(
        [np.stack([i, i + n, i1 + n], 1), np.stack([i, i1 + n, i1], 1)]
    )
    top_o = (nv - 1) * nu + i
    top_o1 = (nv - 1) * nu + i1
    top = np.vstack(
        [
            np.stack([top_o, top_o1, top_o1 + n], 1),
            np.stack([top_o, top_o1 + n, top_o + n], 1),
        ]
    )

    faces = np.vstack([outer_faces, inner_faces, bottom, top]).astype(np.int64)
    faces = _flip_if_inverted(vertices, faces)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _side_chord(radius: float, tolerance: float) -> float:
    """Longest ring edge whose bow stays inside `tolerance`.

    A prism's side wall is a straight chord where the hole's edge is really a
    curve on the surface, so the wall bows into the strut by the sagitta of
    that chord. Two neighbouring holes bow toward each other, and on a thin
    strut that is enough to meet in the middle and cut it.
    """
    tolerance = min(tolerance, radius)
    return 2.0 * float(np.sqrt(max(tolerance * (2.0 * radius - tolerance), 0.0)))


def _affordable_chord(radius: float, max_clear: float) -> float:
    """Longest flat chord whose bulge still fits inside the clearance budget.

    A flat triangle laid across a curved wall dips below it by the sagitta of
    its own longest edge. Inverting `clear = overshoot + margin * sagitta`
    gives the edge length a prism cap may use before it would have to stand
    further out than the cover can afford.
    """
    budget = (max_clear - WALL_OVERSHOOT) / SAGITTA_MARGIN
    if budget <= 0.0:
        return WALL_OVERSHOOT
    budget = min(budget, radius)
    return 0.8 * float(np.sqrt(budget * (2.0 * radius - budget)))


def _densify(ring: np.ndarray, edge_mm: np.ndarray, chord: float) -> np.ndarray:
    """Split any ring edge longer than `chord`, in parameter space."""
    if not np.any(edge_mm > chord):
        return ring
    out = []
    nxt = np.roll(ring, -1, axis=0)
    for a, b, length in zip(ring, nxt, edge_mm):
        steps = max(1, int(np.ceil(length / chord)))
        for k in range(steps):
            out.append(a + (b - a) * (k / steps))
    return np.array(out)


def hole_prisms(
    surface: Surface,
    holes: list[np.ndarray],
    thickness: float,
    curvature_radius: float,
    max_clear: float,
    chord_tolerance: float,
) -> trimesh.Trimesh | None:
    """One mesh holding every cutting prism as a separate closed component.

    A prism's caps are flat while the wall they cut through is curved, so a cap
    has to start outside the wall's own bulge or the middle of a wide hole
    keeps a thin lens of material that floats free of the cover. Rather than
    standing every cap far enough out, which on a slim cover would drive the
    prism into the opposite wall, each cap is laid on the surface itself and
    subdivided until no triangle is longer than the wall's curvature can
    afford. A hole small enough needs no subdivision at all.

    The same subdivision keeps the side walls honest. A wall is a straight
    chord where the hole's edge is really a curve, so it bows into the strut;
    two neighbours bow toward each other and on a thin strut that is enough to
    meet in the middle. `chord_tolerance` is how much of the strut that bow may
    take, and `pattern` has already widened its erosion by the same amount.

    A cell's own hole is convex, and a cone of triangles from its centre is the
    cheapest cap that covers it. A motif's hole is whatever the picture was, and
    a cone from any single point can fold over itself on a shape like a letter
    C. Those get a triangulated cap instead. Which builder a ring goes to is
    read off the ring, so a motif that happens to be convex costs nothing extra.
    """
    rings = [r[::-1] if _signed_area(r) < 0 else r for r in holes if len(r) >= 3]
    if not rings:
        return None

    chord = min(
        _affordable_chord(curvature_radius, max_clear),
        _side_chord(curvature_radius, chord_tolerance),
    )

    convex = [r for r in rings if _is_convex(r)]
    rest = [r for r in rings if not _is_convex(r)]
    parts = [
        build(surface, group, thickness, curvature_radius, max_clear, chord)
        for group, build in ((convex, _cone_prisms), (rest, _meshed_prisms))
        if group
    ]
    parts = [m for m in parts if m is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    counts = np.cumsum([0] + [len(m.vertices) for m in parts[:-1]])
    return trimesh.Trimesh(
        vertices=np.vstack([m.vertices for m in parts]),
        faces=np.vstack([m.faces + off for m, off in zip(parts, counts)]).astype(np.int64),
        process=False,
    )


def _is_convex(ring: np.ndarray) -> bool:
    """True when a counter-clockwise ring never turns the other way."""
    a = ring
    b = np.roll(ring, -1, axis=0)
    c = np.roll(ring, -2, axis=0)
    cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - b[:, 1]) - (b[:, 1] - a[:, 1]) * (
        c[:, 0] - b[:, 0]
    )
    return bool(np.all(cross >= -1e-12 * max(float(np.abs(cross).max()), 1.0)))


def _cone_prisms(
    surface: Surface,
    rings: list[np.ndarray],
    thickness: float,
    curvature_radius: float,
    max_clear: float,
    chord: float,
) -> trimesh.Trimesh | None:
    """Prisms whose caps are cones of triangles from each ring's centre."""
    # Pass one: measure each ring on the real surface.
    lens = np.array([len(r) for r in rings])
    start = np.concatenate([[0], np.cumsum(lens)[:-1]])
    flat = np.vstack(rings)
    mids = np.array([r.mean(axis=0) for r in rings])
    probe = surface.point(flat[:, 0], flat[:, 1])
    centres = surface.point(mids[:, 0], mids[:, 1])
    owner = np.repeat(np.arange(len(rings)), lens)
    reach = np.maximum.reduceat(np.linalg.norm(probe - centres[owner], axis=1), start)
    edges = np.linalg.norm(np.roll(probe, -1, axis=0) - probe, axis=1)

    # Pass two: lay out the cap samples each ring turned out to need.
    samples: list[np.ndarray] = []
    levels: list[int] = []
    widths: list[int] = []
    spans: list[float] = []
    for i, ring in enumerate(rings):
        m = lens[i]
        edge = edges[start[i] : start[i] + m].copy()
        edge[-1] = np.linalg.norm(probe[start[i]] - probe[start[i] + m - 1])
        dense = _densify(ring, edge, chord)
        L = max(1, int(np.ceil(reach[i] / chord)))
        centre = mids[i]
        rows = [centre + (dense - centre) * ((j + 1) / L) for j in range(L)]
        samples.append(np.vstack([centre[None, :], *rows]))
        levels.append(L)
        widths.append(len(dense))
        spans.append(max(reach[i] / L, float(min(edge.max(), chord))))

    span = np.array(spans)
    bulge = curvature_radius - np.sqrt(np.maximum(curvature_radius**2 - span**2, 0.0))
    clear = np.minimum(WALL_OVERSHOOT + SAGITTA_MARGIN * bulge, max_clear)
    depth = thickness + 2.0 * clear

    grid = np.vstack(samples)
    p, n = surface.frame(grid[:, 0], grid[:, 1])
    counts = np.array([len(s) for s in samples])
    who = np.repeat(np.arange(len(rings)), counts)
    top = p + n * clear[who, None]
    bot = top - n * depth[who, None]

    verts: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    base = 0
    offset = 0
    for i in range(len(rings)):
        count = int(counts[i])
        L, m = levels[i], widths[i]
        verts.append(np.vstack([top[offset : offset + count], bot[offset : offset + count]]))
        faces.append(_prism_faces(L, m, count) + base)
        base += 2 * count
        offset += count

    return trimesh.Trimesh(
        vertices=np.vstack(verts), faces=np.vstack(faces).astype(np.int64), process=False
    )


def _prism_faces(levels: int, width: int, count: int) -> np.ndarray:
    """Triangles for one prism: cone cap, matching cap below, and the sides."""
    i = np.arange(width)
    i1 = (i + 1) % width

    def top(level: int) -> np.ndarray:
        return 1 + level * width + i

    def top1(level: int) -> np.ndarray:
        return 1 + level * width + i1

    parts = [np.stack([np.zeros_like(i), top(0), top1(0)], 1)]
    for j in range(levels - 1):
        parts.append(np.stack([top(j), top(j + 1), top1(j + 1)], 1))
        parts.append(np.stack([top(j), top1(j + 1), top1(j)], 1))
    cap = np.vstack(parts)
    # The far cap is the same surface, wound the other way.
    parts_bot = cap[:, ::-1] + count
    outer, outer1 = top(levels - 1), top1(levels - 1)
    sides = np.vstack(
        [
            np.stack([outer, outer + count, outer1 + count], 1),
            np.stack([outer, outer1 + count, outer1], 1),
        ]
    )
    return np.vstack([cap, parts_bot, sides])


MAX_REFINEMENTS = 6
"""Rounds of cap refinement. Each one at least halves every edge it splits, so
this reaches a chord sixty times finer than the ring it started from."""


def _meshed_prisms(
    surface: Surface,
    rings: list[np.ndarray],
    thickness: float,
    curvature_radius: float,
    max_clear: float,
    chord: float,
) -> trimesh.Trimesh | None:
    """Prisms whose caps are triangulated, for rings that are not convex.

    A constrained Delaunay triangulation fills the ring exactly, using the
    ring's own vertices and no others, so the cap's edge *is* the hole's edge.
    What it does not do is keep its triangles small, and a flat triangle laid
    across a curved wall dips below it by the sagitta of its longest edge. So
    the triangulation is then refined until nothing is longer than the same
    chord the cone caps obey.

    Refinement is red-green: mark every edge that is too long, then mark the
    third edge of any triangle that has two marked, until nothing changes. A
    triangle with three marked edges becomes four and one with a single marked
    edge becomes two, so no vertex ever lands in the middle of a neighbour's
    edge and the cap stays a closed surface.
    """
    dense: list[np.ndarray] = []
    for ring in rings:
        probe = surface.point(ring[:, 0], ring[:, 1])
        edge = np.linalg.norm(np.roll(probe, -1, axis=0) - probe, axis=1)
        dense.append(_densify(ring, edge, chord))

    built = _triangulate(dense)
    if built is None:
        return None
    uv, tris, vown = built

    def on_surface(q: np.ndarray) -> np.ndarray:
        return surface.point(q[:, 0], q[:, 1])

    uv, tris, vown = _refine(uv, tris, vown, on_surface, chord)

    point, normal = surface.frame(uv[:, 0], uv[:, 1])
    edges = np.stack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=1)
    length = np.linalg.norm(point[edges[..., 0]] - point[edges[..., 1]], axis=-1)

    # A prism stands out by what its own widest triangle can dip, exactly as a
    # cone cap does, so nothing about the clearance budget changes here.
    span = np.zeros(len(rings))
    np.maximum.at(span, vown[tris[:, 0]], length.max(axis=1))
    bulge = curvature_radius - np.sqrt(np.maximum(curvature_radius**2 - span**2, 0.0))
    clear = np.minimum(WALL_OVERSHOOT + SAGITTA_MARGIN * bulge, max_clear)
    depth = thickness + 2.0 * clear

    count = len(uv)
    top = point + normal * clear[vown][:, None]
    bot = top - normal * depth[vown][:, None]

    # Every prism is its own connected component already: rings share no
    # vertices, and refinement only ever splits an edge inside one of them.
    side = _boundary_edges(tris)
    a, b = side[:, 0], side[:, 1]
    faces = np.vstack(
        [
            tris,
            tris[:, ::-1] + count,
            np.stack([a, a + count, b + count], axis=1),
            np.stack([a, b + count, b], axis=1),
        ]
    )
    return trimesh.Trimesh(
        vertices=np.vstack([top, bot]), faces=faces.astype(np.int64), process=False
    )


def _triangulate(
    rings: list[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """One constrained Delaunay triangulation per ring, in one index space.

    The triangulation uses each ring's own vertices and hands them straight
    back, so the triangles are matched to the ring by coordinate rather than
    by any index the library kept. Doing that for every ring at once, with the
    ring's number as part of the key, is what keeps this off a Python loop
    over a few hundred thousand triangles.
    """
    size = np.array([len(r) for r in rings])
    uv = np.vstack(rings)
    vown = np.repeat(np.arange(len(rings)), size)

    cells = np.atleast_1d(constrained_delaunay_triangles([Polygon(r) for r in rings]))
    per_ring = get_num_geometries(cells)
    if not per_ring.sum():
        return None
    # A triangle comes back as a closed ring of four coordinates.
    corners = get_coordinates(cells).reshape(-1, 4, 2)[:, :3, :].reshape(-1, 2)
    town = np.repeat(np.repeat(np.arange(len(rings)), per_ring), 3)

    rows = np.vstack(
        [
            np.column_stack([vown, uv]),
            np.column_stack([town, corners]),
        ]
    )
    _, back = np.unique(rows, axis=0, return_inverse=True)
    back = back.ravel()
    lookup = np.full(int(back.max()) + 1, -1, dtype=np.int64)
    lookup[back[: len(uv)]] = np.arange(len(uv))
    tris = lookup[back[len(uv) :]].reshape(-1, 3)

    a, b, c = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    turn = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (
        c[:, 0] - a[:, 0]
    )
    keep = (tris.min(axis=1) >= 0) & (turn != 0.0)
    tris, turn = tris[keep], turn[keep]
    if not len(tris):
        return None
    flip = turn < 0.0
    tris[flip] = tris[flip][:, [0, 2, 1]]
    return uv, tris, vown


def _refine(
    uv: np.ndarray,
    tris: np.ndarray,
    vown: np.ndarray,
    place,
    target: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split triangles until no edge on the surface is longer than `target`."""
    for _ in range(MAX_REFINEMENTS):
        point = place(uv)
        ends = np.stack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=1)
        key = np.minimum(ends[..., 0], ends[..., 1]).astype(np.int64) * len(uv) + np.maximum(
            ends[..., 0], ends[..., 1]
        )
        unique, back = np.unique(key, return_inverse=True)
        back = back.reshape(key.shape)
        long_enough = (
            np.linalg.norm(point[ends[..., 0]] - point[ends[..., 1]], axis=-1) > target
        )
        marked = np.zeros(len(unique), dtype=bool)
        np.logical_or.at(marked, back, long_enough)
        if not marked.any():
            break

        # Closure: a triangle with two marked edges takes the third as well,
        # which is what keeps the split patterns down to four-ways and halves.
        while True:
            pair = marked[back].sum(axis=1) == 2
            if not pair.any():
                break
            marked[back[pair]] = True

        chosen = np.nonzero(marked)[0]
        lo, hi = unique[chosen] // len(uv), unique[chosen] % len(uv)
        middle = np.full(len(unique), -1, dtype=np.int64)
        middle[chosen] = len(uv) + np.arange(len(chosen))
        uv = np.vstack([uv, (uv[lo] + uv[hi]) / 2.0])
        vown = np.concatenate([vown, vown[lo]])

        split = marked[back]
        mid = middle[back]
        how = split.sum(axis=1)
        parts = [tris[how == 0]]
        four = how == 3
        if four.any():
            t, m = tris[four], mid[four]
            parts += [
                np.stack([t[:, 0], m[:, 0], m[:, 2]], axis=1),
                np.stack([t[:, 1], m[:, 1], m[:, 0]], axis=1),
                np.stack([t[:, 2], m[:, 2], m[:, 1]], axis=1),
                np.stack([m[:, 0], m[:, 1], m[:, 2]], axis=1),
            ]
        for k in range(3):
            half = (how == 1) & split[:, k]
            if not half.any():
                continue
            t, m = tris[half], mid[half][:, k]
            i, j, far = t[:, k], t[:, (k + 1) % 3], t[:, (k + 2) % 3]
            parts += [
                np.stack([i, m, far], axis=1),
                np.stack([m, j, far], axis=1),
            ]
        tris = np.vstack(parts)
    return uv, tris, vown


def _boundary_edges(tris: np.ndarray) -> np.ndarray:
    """Directed edges used by one triangle only, still wound with it."""
    ends = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    span = int(tris.max()) + 1
    key = np.minimum(ends[:, 0], ends[:, 1]).astype(np.int64) * span + np.maximum(
        ends[:, 0], ends[:, 1]
    )
    _, back, counts = np.unique(key, return_inverse=True, return_counts=True)
    return ends[counts[back] == 1]


def _signed_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


# --- manifold3d bridge --------------------------------------------------


def to_manifold(mesh: trimesh.Trimesh) -> Manifold:
    return Manifold(
        Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )


def from_manifold(man: Manifold) -> trimesh.Trimesh:
    m = man.to_mesh()
    verts = np.asarray(m.vert_properties[:, :3], dtype=np.float64)
    faces = np.asarray(m.tri_verts, dtype=np.int64)
    # to_mesh() hands back positions still split along the merge vectors, so a
    # naive read would see one component per triangle fan. Applying the
    # vectors is far cheaper than letting trimesh rediscover them.
    merge_from = np.asarray(m.merge_from_vert, dtype=np.int64)
    if merge_from.size:
        remap = np.arange(len(verts))
        remap[merge_from] = np.asarray(m.merge_to_vert, dtype=np.int64)
        faces = remap[faces]
    keep = np.zeros(len(verts), dtype=bool)
    keep[faces] = True
    renumber = np.cumsum(keep) - 1
    return trimesh.Trimesh(
        vertices=verts[keep], faces=renumber[faces], process=False
    )


def perforate(solid: trimesh.Trimesh, prisms: trimesh.Trimesh | None) -> Manifold:
    body = to_manifold(solid)
    if prisms is None:
        return body
    return Manifold.batch_boolean([body, to_manifold(prisms)], OpType.Subtract)


def split_halves(body: Manifold, clearance: float) -> Manifold:
    """Cut the cover down the seam into two halves with a fitting gap.

    A plane through a lattice sometimes lifts a strut junction clear of both
    halves. Each half keeps only its own connected body, so the result is
    always exactly two pieces.
    """
    lo, hi = np.array(body.bounding_box(), dtype=float).reshape(2, 3)
    size = (hi - lo) * 2.0 + 20.0
    gap = clearance / 2.0
    pieces = []
    for sign in (1.0, -1.0):
        box = Manifold.cube(size.tolist(), center=True)
        centre = (lo + hi) / 2.0
        centre[1] = sign * (gap + size[1] / 2.0)
        half = body ^ box.translate(centre.tolist())
        parts = half.decompose()
        if len(parts) > 1:
            half = max(parts, key=lambda m: m.volume())
        pieces.append(half)
    return Manifold.batch_boolean(pieces, OpType.Add)


# --- slabs: a region of the surface, given a thickness ---------------------

SLAB_SIMPLIFY = 1e-4
"""Outline simplification in (u, v) before a slab is triangulated: about a
twentieth of a millimetre on a leg."""


def slab(
    surface,
    region: Polygon,
    outer,
    inner,
    chord: float,
) -> trimesh.Trimesh | None:
    """A closed solid over a patch of the surface, between two offsets.

    `region` is a polygon in (u, v), holes allowed. `outer` and `inner` give
    the offset along the outward normal, in mm, of the two faces: numbers, or
    functions of an (n, 2) array of (u, v). A half of the cover is a slab from
    0 to -wall; a shelf under a seam is a slab from -a to -b.

    The prism caps get away with a constrained triangulation of their own
    outline because a hole is small. A half of a cover is not: a triangulation
    of its outline alone is a fan of slivers two hundred millimetres long, and
    splitting slivers only makes more of them. So the face is seeded inside
    with points a chord apart, laid out in millimetres, and triangulated with
    them; the outline is sampled twice as finely so its edges survive.
    """
    region = region.simplify(SLAB_SIMPLIFY, preserve_topology=True)
    if region.is_empty or region.area <= 0:
        return None
    built = _seeded_triangulation(surface, region, chord)
    if built is None:
        return None
    uv, tris = built
    point, normal = surface.frame(uv[:, 0], uv[:, 1])

    def offset(spec) -> np.ndarray:
        value = spec(uv) if callable(spec) else spec
        return np.broadcast_to(np.asarray(value, dtype=float), (len(uv),))

    top = point + normal * offset(outer)[:, None]
    bot = point + normal * offset(inner)[:, None]
    n = len(uv)
    side = _boundary_edges(tris)
    s0, s1 = side[:, 0], side[:, 1]
    faces = np.vstack(
        [
            tris,
            tris[:, ::-1] + n,
            np.stack([s0, s0 + n, s1 + n], axis=1),
            np.stack([s0, s1 + n, s1], axis=1),
        ]
    ).astype(np.int64)
    vertices = np.vstack([top, bot])
    faces = _flip_if_inverted(vertices, faces)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _seeded_triangulation(surface, region: Polygon, chord: float):
    """Triangles over `region` with edges about `chord` long on the surface.

    Worked in a chart scaled to millimetres at the region's middle. The scale
    drifts across a large region, so the result is then refined on the real
    surface, which from well-shaped triangles only splits a few.
    """
    from scipy.spatial import Delaunay
    from shapely import contains_xy

    c = region.representative_point()
    e = 1e-4
    p0 = surface.point(c.x, c.y)
    sx = float(np.linalg.norm(surface.point(c.x + e, c.y) - p0) / e)
    sy = float(np.linalg.norm(surface.point(c.x, min(c.y + e, 1.0)) - p0) / e)
    scale = np.array([sx, sy])

    rings = [np.asarray(region.exterior.coords)[:-1]] + [
        np.asarray(r.coords)[:-1] for r in region.interiors
    ]
    border = []
    for ring in rings:
        probe = surface.point(ring[:, 0], ring[:, 1])
        edge = np.linalg.norm(np.roll(probe, -1, axis=0) - probe, axis=1)
        ring = _densify(ring, edge, chord / 2.0)
        # The chart's scale is the region's middle, and the leg is wider or
        # narrower elsewhere: the outline must be fine in the chart as well.
        flat = np.linalg.norm((np.roll(ring, -1, axis=0) - ring) * scale, axis=1)
        ring = _densify(ring, flat, chord / 2.0)
        # A repeated point is dropped by the triangulation, which then walks
        # the outline through its twin the wrong way round.
        step = np.linalg.norm((np.roll(ring, -1, axis=0) - ring) * scale, axis=1)
        border.append(ring[step > 1e-6])
    border_uv = np.vstack(border)
    _, first = np.unique(np.round(border_uv * scale, 6), axis=0, return_index=True)
    if len(first) != len(border_uv):
        return _constrained_triangulation(surface, border, chord)

    chart = Polygon(*(lambda rs: (rs[0] * scale, [r * scale for r in rs[1:]]))(border))
    inner = chart.buffer(-0.7 * chord)
    seeds = np.zeros((0, 2))
    if not inner.is_empty:
        x0, y0, x1, y1 = inner.bounds
        h = chord * np.sqrt(3.0) / 2.0
        ys = np.arange(y0, y1 + h, h)
        xs = np.arange(x0, x1 + chord, chord)
        gx, gy = np.meshgrid(xs, ys)
        gx = gx + (np.arange(len(ys))[:, None] % 2) * chord / 2.0
        pts = np.stack([gx.ravel(), gy.ravel()], axis=1)
        seeds = pts[contains_xy(inner, pts[:, 0], pts[:, 1])]

    points = np.vstack([border_uv * scale, seeds])
    tri = Delaunay(points).simplices
    cent = points[tri].mean(axis=1)
    tri = tri[contains_xy(chart, cent[:, 0], cent[:, 1])]
    if not len(tri):
        return None

    uv = points / scale
    # Measured in the chart, in square millimetres: a triangle laid along a
    # straight run of the outline has next to no area, and halving it later
    # can turn its sign over in floating point.
    a, b, cc = points[tri[:, 0]], points[tri[:, 1]], points[tri[:, 2]]
    turn = (b[:, 0] - a[:, 0]) * (cc[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (cc[:, 0] - a[:, 0])
    solid = np.abs(turn) > 1e-3 * chord * chord
    tri, turn = tri[solid], turn[solid]
    tri[turn < 0.0] = tri[turn < 0.0][:, [0, 2, 1]]

    # Every border point must have made it into the triangulation's outline
    # the same number of times as it sits on a ring, or the outline did not
    # survive and the slower, sure route is taken.
    tri = _untie(tri)
    lost = abs(len(_boundary_edges(tri)) - len(border_uv))
    if lost > 0.02 * len(border_uv) or not _is_disc_like(tri):
        return _constrained_triangulation(surface, border, chord)

    def on_surface(q: np.ndarray) -> np.ndarray:
        return surface.point(q[:, 0], q[:, 1])

    uv, tri, _ = _refine(uv, tri, np.zeros(len(uv), dtype=np.int64), on_surface, chord * 1.5)
    return uv, tri


def _untie(tris: np.ndarray, rounds: int = 6) -> np.ndarray:
    """Open every pinch where two fans of triangles meet at one vertex.

    A narrow neck in an outline can come out of the triangulation as two
    triangles touching corner to corner, and a solid built on that is not a
    manifold. The triangles on the outline at such a vertex are dropped, which
    narrows the neck by one triangle and nothing else.
    """
    for _ in range(rounds):
        if len(tris) == 0:
            return tris
        side = _boundary_edges(tris)
        starts = np.bincount(side[:, 0], minlength=int(tris.max()) + 1)
        tied = np.nonzero(starts > 1)[0]
        if not len(tied):
            return tris
        on_outline = np.zeros(len(starts), dtype=bool)
        on_outline[side[:, 0]] = True
        ends = np.stack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=1)
        span = int(tris.max()) + 1
        key = np.minimum(ends[..., 0], ends[..., 1]).astype(np.int64) * span + np.maximum(ends[..., 0], ends[..., 1])
        skey = np.minimum(side[:, 0], side[:, 1]).astype(np.int64) * span + np.maximum(side[:, 0], side[:, 1])
        touches_outline = np.isin(key, skey).any(axis=1)
        at_tie = np.isin(tris, tied).any(axis=1)
        tris = tris[~(at_tie & touches_outline)]
    return tris


def _is_disc_like(tris: np.ndarray) -> bool:
    """No vertex where two fans of triangles touch at a single point."""
    side = _boundary_edges(tris)
    starts = np.bincount(side[:, 0], minlength=int(tris.max()) + 1)
    return bool(starts.max(initial=0) <= 1)


def _constrained_triangulation(surface, border: list[np.ndarray], chord: float):
    shape = Polygon(border[0], border[1:])
    if not shape.is_valid or shape.area <= 0:
        return None
    uv = np.vstack(border)
    cells = constrained_delaunay_triangles(shape)
    if not get_num_geometries(cells):
        return None
    corners = get_coordinates(cells).reshape(-1, 4, 2)[:, :3, :].reshape(-1, 2)
    rows = np.vstack([uv, corners])
    _, back = np.unique(rows, axis=0, return_inverse=True)
    back = back.ravel()
    lookup = np.full(int(back.max()) + 1, -1, dtype=np.int64)
    lookup[back[: len(uv)]] = np.arange(len(uv))
    tris = lookup[back[len(uv) :]].reshape(-1, 3)
    a, b, c = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    turn = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    keep = (tris.min(axis=1) >= 0) & (turn != 0.0)
    tris, turn = tris[keep], turn[keep]
    tris[turn < 0.0] = tris[turn < 0.0][:, [0, 2, 1]]

    def on_surface(q: np.ndarray) -> np.ndarray:
        return surface.point(q[:, 0], q[:, 1])

    uv, tris, _ = _refine(uv, tris, np.zeros(len(uv), dtype=np.int64), on_surface, chord)
    return uv, tris
