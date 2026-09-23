"""A cover built on the Rhino model, from its parameters to one printable body.

The shape is not drawn here and cannot be: it is `cover ready iteration 1.stl`,
measured once into a radius over (angle, height).  What this adds to it is the
wall, and the pattern — the same cell field, operation, mask and motif the
other covers carry, laid on this surface instead of a drawn or scanned one.

The rims are the one thing the pattern has to be told about.  On a tube they
are two circles and a plain band along each is enough; here the top rim runs
from 323 mm at the back of the knee to 457 at the sides, so the band follows
the curve.  Cells fade out toward it, and a hole is kept only if its whole
outline stays clear of it, so the band beside an edge is plainly solid rather
than sprinkled with chips.

As in the other generators, nothing here refuses a design.  Where a limit
binds it is absorbed, reported in `notes`, and sent to the panel as the new
end of that slider's track.
"""

from __future__ import annotations

import math

import logging
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import polylabel
import trimesh

from .. import mesh_build as mb
from .. import motif as mo
from .. import relief as rl
from ..fields import as_array_field, density_from, mask_from
from ..pattern import Placement, build_cells, build_pattern
from ..printer_profile import DEFAULT_PROFILE, PrinterProfile
from ..surface import TWO_PI
from . import config as cfg
from . import mesh as im
from .params import ITER_RANGES, IterParams
from .surface import IterSurface

log = logging.getLogger("cover.iteration1")


@dataclass
class Quality:
    rows: int
    quad_segs: int
    chord_tolerance: float = 0.05
    """How much of a strut a prism's flat wall may bow into, as a fraction of
    it.  The same in a draft as in a final: the curvature of the model caps
    the prism's chord well below this either way, so loosening it buys a
    draft nothing."""


DRAFT = Quality(rows=cfg.DRAFT_ROWS, quad_segs=2)
FINAL = Quality(rows=cfg.ROWS, quad_segs=3)


@dataclass
class IterCover:
    mesh: trimesh.Trimesh
    params: IterParams
    profile: PrinterProfile
    volume_mm3: float = 0.0
    plain_volume_mm3: float = 0.0
    mass_g: float = 0.0
    plain_mass_g: float = 0.0
    saving_pct: float = 0.0
    holes: int = 0
    wall: float = 0.0
    max_wall: float = 0.0
    max_relief: float = 0.0
    notes: list[str] = field(default_factory=list)
    limits: dict[str, tuple[float, float]] = field(default_factory=dict)
    surface: IterSurface = field(repr=False, default=None)
    rings: list = field(repr=False, default_factory=list)
    """The holes as outlines in (u, v), kept so a check can be made on the
    pattern itself rather than inferred back off the mesh."""


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _placement(p: IterParams) -> Placement | None:
    motif = mo.resolve(p)
    if motif is None:
        return None
    return Placement(
        shape=motif.solid,
        fill=p.motif_fill,
        rotation=p.motif_rotation,
        rotation_jitter=p.motif_rotation_jitter,
        align_flow=p.motif_align_flow,
        scale_jitter=p.motif_scale_jitter,
        flow_angle=p.flow_angle,
        seed=p.seed,
    )


def _densify_uv(ring: np.ndarray, factor: int) -> np.ndarray:
    """A ring with `factor` samples along every edge, for reading a field."""
    nxt = np.roll(ring, -1, axis=0)
    steps = np.linspace(0.0, 1.0, factor, endpoint=False)[:, None, None]
    return (ring[None] + (nxt - ring)[None] * steps).reshape(-1, 2)


def _hole_size(ring: np.ndarray, centre: np.ndarray, surface: IterSurface) -> tuple[float, float]:
    """Width and length of a hole, mm: the widest circle it holds, and the
    longer side of the smallest box around it.

    The same measure the transfemoral tab uses, and for its reason.  Half the
    distance from the centroid to the nearest point of the outline -- which is
    what this used to take for the width -- is not the widest circle a hole
    holds: a cell the fade has eaten is concave, its centroid can sit outside
    it altogether, and a splinter then measures wide enough to keep.  The pole
    of inaccessibility is the width, and the smallest rotated box gives the
    length the aspect rule is against.

    The ring is in (u, v); one unit of either is worth a different number of
    millimetres and that changes along the cover, so it is measured at the
    hole's own place on the surface.
    """
    e = 1e-4
    p0 = surface.point(centre[0], centre[1])
    su = float(np.linalg.norm(surface.point(centre[0] + e, centre[1]) - p0) / e)
    sv = float(np.linalg.norm(surface.point(centre[0], min(centre[1] + e, 1.0)) - p0) / e)
    poly = Polygon(np.stack([ring[:, 0] * su, ring[:, 1] * sv], axis=1))
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.geom_type != "Polygon" or poly.area <= 0.0:
        return 0.0, 0.0
    try:
        inside = polylabel(poly, tolerance=0.03 * math.sqrt(poly.area))
    except Exception:
        return 0.0, 0.0
    width = 2.0 * poly.exterior.distance(inside)
    box = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)
    sides = np.linalg.norm(np.diff(box, axis=0), axis=1)
    return width, float(sides.max()) if len(sides) else width


def generate(
    params: IterParams,
    *,
    quality: Quality = FINAL,
    profile: PrinterProfile = DEFAULT_PROFILE,
    keep_clear=None,
    extra_holes=None,
) -> IterCover:
    """`keep_clear(u, v)` returns how far a point is from anything that has to
    stay solid, in millimetres, negative inside it.

    The tab that puts fasteners on this cover passes one: a land needs wall
    under it and a clamp's web needs wall to land on, and a hole in either
    place is a hole in the part that holds the cover on.  Without it the
    cover is patterned to its own rims and nothing else, which is what the
    tab without fasteners wants."""
    p = params.clamped()
    notes: list[str] = []
    limits: dict[str, tuple[float, float]] = {}
    surface = IterSurface.default(p.surface_smoothing, p.shape, p.model)

    max_wall = surface.max_wall_thickness(profile, ITER_RANGES["wall_thickness"].hi)
    limits["wall_thickness"] = (ITER_RANGES["wall_thickness"].lo, max_wall)
    wall = min(p.wall_thickness, max_wall)
    if wall < p.wall_thickness - 1e-6:
        notes.append(f"Wall held at {wall:.1f} mm by the curve of the model")
    if abs(wall - surface.wall) > 0.05:
        notes.append(f"Model was drawn with a {surface.wall:.1f} mm wall")

    strut = max(p.strut_width, profile.MIN_STRUT)
    if p.cuts_through and strut > p.strut_width + 1e-6:
        notes.append(f"Struts widened to {strut:.1f} mm")

    max_relief = rl.max_depth(wall, p.operation == "engrave", ITER_RANGES["relief_depth"].hi)
    if p.operation == "engrave":
        max_relief = max(min(max_relief, wall - profile.MIN_STRUT), 0.0)
    depth = min(p.relief_depth, max_relief)
    if p.has_relief and depth < p.relief_depth - 1e-6:
        notes.append(f"Relief held at {depth:.1f} mm by the wall")

    # --- the rims, as a mask and as a keep-out ------------------------------
    # Both are read straight off the rim curves, which the surface carries, so
    # no grid stands between where the cover ends and where a hole may go.
    def edge_mask(u, v):
        return _smoothstep((surface.edge_distance(u, v) - p.rim_solid) / cfg.EDGE_FADE)

    def keep_at(u, v):
        return surface.edge_distance(u, v) - p.rim_solid - strut

    design_mask = as_array_field(mask_from(p))

    if keep_clear is not None:
        rim_fade, rim_keep = edge_mask, keep_at

        def edge_mask(u, v):
            d = np.asarray(keep_clear(u, v), dtype=float)
            return rim_fade(u, v) * _smoothstep(d / cfg.EDGE_FADE)

        def keep_at(u, v):
            return np.minimum(rim_keep(u, v), np.asarray(keep_clear(u, v), dtype=float) - strut)

    def mask(u, v):
        return design_mask(u, v) * np.clip(edge_mask(u, v), 0.0, 1.0)

    # --- the cell field ------------------------------------------------------
    cells = None
    if p.operation != "none":
        cells = build_cells(
            surface,
            density_from(p),
            wall_thickness=wall,
            strut=strut,
            irregularity=p.irregularity,
            anisotropy=p.anisotropy,
            flow_angle=p.flow_angle,
            profile=profile,
            rng=np.random.default_rng(p.seed),
        )

    rings: list[np.ndarray] = []
    if p.operation == "cut":
        placement = _placement(p)
        if placement is not None:
            notes.extend(mo.resolve(p).notes)
        pattern = build_pattern(
            cells,
            mask,
            profile=profile,
            corner_radius=p.corner_radius,
            quad_segs=quality.quad_segs,
            chord_tolerance=quality.chord_tolerance * strut,
            placement=placement,
        )
        dropped = 0
        for ring in pattern.holes:
            dense = _densify_uv(ring, 8)
            if float(np.min(keep_at(dense[:, 0], dense[:, 1]))) < cfg.KEEP_MARGIN:
                dropped += 1
                continue
            centre = ring.mean(axis=0)
            width, length = _hole_size(ring, centre, surface)
            strength = float(edge_mask(centre[0], centre[1]))
            faded = strength < 0.999
            if (
                strength < cfg.FADE_KEEP
                or width < cfg.MIN_TIDY_HOLE
                or (faded and width < cfg.TIDY_ASPECT * length)
            ):
                dropped += 1
                continue
            rings.append(ring)
        if extra_holes is not None:
            # Large motifs the cell field would only blur.  They come with the
            # ground they need: cells inside it come out, so the drawing reads
            # against solid wall instead of against more holes.
            added, added_notes, keepout = extra_holes(surface, cells, strut)
            notes.extend(added_notes)
            if added:
                if keepout is not None and rings:
                    centres = np.array([r.mean(axis=0) for r in rings])
                    if callable(keepout):
                        # The whole of a region belongs to the drawing -- which
                        # is what the transfemoral tab does, giving the leaves
                        # its entire back half.  Cells beside a leaf do not
                        # frame it, they turn it into noise.
                        hit = np.asarray(keepout(centres), dtype=bool)
                    else:
                        u_lo, u_hi, v_lo, v_hi = keepout
                        du = (centres[:, 0] - (u_lo + u_hi) / 2.0 + 0.5) % 1.0 - 0.5
                        hit = ((np.abs(du) < (u_hi - u_lo) / 2.0)
                               & (centres[:, 1] > v_lo) & (centres[:, 1] < v_hi))
                    rings = [r for r, bad in zip(rings, hit) if not bad]
                rings.extend(added)
        if pattern.subdivided:
            notes.append(f"Pattern refined across {pattern.subdivided} cells for stiffness")
        if dropped:
            notes.append(f"{dropped} cells at the rims left solid")
        if p.hole_shape == "image" and placement is None:
            notes.append("No picture held, cells used")
    elif p.operation == "none":
        notes.append("Smooth shell, no pattern")

    # --- the solid -----------------------------------------------------------
    grid = surface.loft_grid(quality.rows)
    rows, cols, _ = grid.shape
    outer = grid
    inner = surface.offset_grid(grid, -wall)
    plain_volume = float(im.shell(outer, inner).volume)

    if p.has_relief and cells is not None:
        u = np.broadcast_to((surface.data.theta % TWO_PI) / TWO_PI, (rows, cols))
        v = surface.v_of_z(grid[..., 2])
        height = rl.height_field(
            cells, mask, u, v, depth=depth, profile=p.relief_profile, length=surface.length
        )
        sign = 1.0 if p.operation == "emboss" else -1.0
        outer = surface.offset_grid(grid, sign * height)

    solid = im.shell(outer, inner)
    holes = 0
    if rings:
        v = np.linspace(0.0, 1.0, 64)
        thinnest = float(np.min(surface.semi_axes(v)[0]))
        prisms = mb.hole_prisms(
            surface,
            rings,
            wall,
            surface.min_curvature_radius(),
            max_clear=0.3 * max(thinnest - wall, 1.0),
            chord_tolerance=quality.chord_tolerance * strut,
        )
        body = mb.perforate(solid, prisms)
        mesh = _largest(mb.from_manifold(body))
        holes = len(rings)
    else:
        mesh = solid

    volume = float(mesh.volume)
    density = p.material_spec.density
    return IterCover(
        mesh=mesh,
        params=p,
        profile=profile,
        volume_mm3=volume,
        plain_volume_mm3=plain_volume,
        mass_g=volume / 1000.0 * density,
        plain_mass_g=plain_volume / 1000.0 * density,
        saving_pct=100.0 * (1.0 - volume / plain_volume) if plain_volume > 0 else 0.0,
        holes=holes,
        wall=wall,
        max_wall=max_wall,
        max_relief=max_relief,
        notes=notes,
        limits=limits,
        surface=surface,
        rings=rings,
    )


def _largest(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """The cover itself, without anything a boolean may have left floating."""
    parts = mesh.split(only_watertight=False)
    return max(parts, key=lambda part: abs(part.volume)) if len(parts) > 1 else mesh


def audit(cover: IterCover) -> list[str]:
    """Full manifold check before anything leaves the building.

    A failure here is a generator bug.  The user never sees it; the log does,
    with the parameters needed to reproduce it.
    """
    m = cover.mesh
    faults = []
    if not m.is_watertight:
        faults.append("not watertight")
    if not m.is_winding_consistent:
        faults.append("winding not consistent")
    if m.body_count != 1:
        faults.append(f"{m.body_count} bodies, expected 1")
    if m.volume <= 0:
        faults.append("volume is not positive")
    if faults:
        log.error(
            "generator produced an unprintable mesh (%s) for params=%r",
            ", ".join(faults),
            cover.params.to_dict(),
        )
    return faults
