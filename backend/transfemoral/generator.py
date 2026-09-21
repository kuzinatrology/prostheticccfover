"""A transfemoral cover, from its parameters to four printable bodies.

    front half   shelves, magnet sockets, the front parts of both clamps
    back half    thickenings, magnet sockets
    lower clamp, back part
    upper clamp, back part

The pattern is the transtibial one, laid on the scan, under one more mask: the
edges. Rims, seams and the notch fade the cells out through the same erosion
the design mask already uses, the notch hardest because it is the edge people
see. On top of the fade a hole is kept only if its whole outline stays a strut
away from every edge, so the strut along an edge is a construction, not a hope.

As in the transtibial generator, nothing here refuses a design. Where a limit
binds it is absorbed, reported in `notes`, and sent to the panel as the new end
of that slider's track.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import trimesh
from manifold3d import Manifold, OpType
from shapely.geometry import Polygon
from shapely.ops import polylabel

from .. import mesh_build as mb
from .. import motif as mo
from .. import relief as rl
from ..fields import as_array_field, density_from, mask_from
from ..pattern import Placement, build_cells, build_pattern
from ..printer_profile import DEFAULT_PROFILE, PrinterProfile
from . import config as cfg
from . import mounts as mt
from .layout import DRAFT_RES, FINAL_RES, Layout, Resolution
from .params import TF_RANGES, TFParams
from .scan_surface import ScanSurface

log = logging.getLogger("cover.transfemoral")

EDGE_FADE = 14.0
"""Width, mm, over which the pattern fades out toward a rim or a seam band."""

NOTCH_FADE = 2.5 * EDGE_FADE
"""The notch is the edge on show, so the pattern leaves it earliest."""

RIM_SOLID = 7.0
"""Plain band at the top and bottom rims, mm."""

KEEP_MARGIN = 0.5
"""Added to every keep-out distance to absorb reading the fields off a grid."""

MIN_TIDY_HOLE = 3.0
"""Smallest hole the pattern may end on, mm across.

A cell caught by the fade erodes from its rim inward, so the last ones before
the pattern stops come out as splinters: two millimetres wide, ten long, and
still inside MIN_HOLE because that rule measures the widest circle a hole
holds. They print, but along a rim or a notch they read as chips in the edge
rather than as holes. Below this the cell is left solid and the pattern ends
on whole cells."""

FADE_KEEP = 0.5
"""How strong the edge mask must be for a cell to be cut at all.

Fading a cell shrinks it, and a boundary made of ever smaller holes crumbles
into chips along every rim, seam and notch. Past this the cell is left solid
instead, so the pattern stops on holes near their full size and the band
beside an edge is plainly solid rather than sprinkled with debris."""

TIDY_ASPECT = 0.35
"""How narrow a hole in the fade may be, as width over length.

Size alone does not catch a splinter: a wedge ten millimetres long can hold a
circle wide enough to pass and still read as a chip. Only holes the fade is
eating are measured this way, so a design of deliberately long cells keeps
them everywhere the pattern is at full strength."""

BODY_NAMES = ("front", "back", "lower_clamp_back", "upper_clamp_back")


@dataclass
class TFQuality:
    res: Resolution
    quad_segs: int


DRAFT = TFQuality(DRAFT_RES, 2)
FINAL = TFQuality(FINAL_RES, 3)


@dataclass
class TFCover:
    params: TFParams
    profile: PrinterProfile
    bodies: dict[str, trimesh.Trimesh]
    volumes: dict[str, float]
    masses: dict[str, float]
    mass_g: float
    plain_mass_g: float
    holes: int
    notes: list[str]
    limits: dict[str, tuple[float, float]]
    wall: float
    strut: float
    max_wall: float
    max_relief: float
    layout: Layout = field(repr=False, default=None)
    magnets: object = field(repr=False, default=None)
    spec: mt.MagnetSpec = field(repr=False, default=None)
    plans: dict = field(repr=False, default_factory=dict)
    pylon: mt.Pylon = field(repr=False, default=None)
    rings: dict = field(repr=False, default_factory=dict)
    keep: object = field(repr=False, default=None)

    @property
    def saving_pct(self) -> float:
        return 100.0 * (1.0 - self.mass_g / self.plain_mass_g) if self.plain_mass_g > 0 else 0.0


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _surface(p: TFParams) -> ScanSurface:
    surface = ScanSurface.default(p.surface_smoothing)
    if surface.region is None:
        from .layout import knee_for

        knee = knee_for(surface)
        surface.region = lambda pts: knee.notch_distance(pts) > 0.0
    return surface


_PLANS: dict[tuple, mt.ClampPlan] = {}


def _plan(name, shape, wanted, layout, spec, pylon, profile, sites, key):
    """Clamp plans are the slow part of a rebuild and change with few sliders."""
    full = (name, shape, key)
    if full not in _PLANS:
        if len(_PLANS) > 32:
            _PLANS.clear()
        _PLANS[full] = mt.plan_clamp(name, shape, wanted, layout, spec, pylon, profile, sites)
    cached = _PLANS[full]
    z = float(np.clip(wanted, cached.lo, cached.hi))
    if cached.ring > 0.0 and abs(z - cached.z) > 0.5:
        found = mt._fit(shape, z, layout, spec, pylon, profile, sites)
        if found is None:
            return cached
        ring, ribs, width = found
        return mt.ClampPlan(name, shape, z, ring, ribs, width, cached.lo, cached.hi, pylon.frame(z))
    return cached


def generate(
    params: TFParams,
    *,
    quality: TFQuality = FINAL,
    profile: PrinterProfile = DEFAULT_PROFILE,
) -> TFCover:
    p = params.clamped()
    notes: list[str] = []
    limits: dict[str, tuple[float, float]] = {}
    res = quality.res
    surface = _surface(p)
    CL = profile.CLEARANCE

    max_wall = surface.max_wall_thickness(profile, TF_RANGES["wall_thickness"].hi)
    wall = min(p.wall_thickness, max_wall)
    if wall < p.wall_thickness - 1e-6:
        notes.append(f"Wall held at {wall:.1f} mm by the curve of the leg")
    strut = max(p.strut_width, profile.MIN_STRUT)
    if p.cuts_through and strut > p.strut_width + 1e-6:
        notes.append(f"Struts widened to {strut:.1f} mm")
    max_relief = rl.max_depth(wall, p.operation == "engrave", TF_RANGES["relief_depth"].hi)
    if p.operation == "engrave":
        # This cover keeps MIN_STRUT of wall everywhere, under a groove too.
        max_relief = max(min(max_relief, wall - profile.MIN_STRUT), 0.0)
    depth = min(p.relief_depth, max_relief)
    if p.has_relief and depth < p.relief_depth - 1e-6:
        notes.append(f"Relief held at {depth:.1f} mm by the wall")

    spec = mt.MagnetSpec(
        diameter=p.magnet_diameter,
        height=p.magnet_height,
        count=p.magnets,
        wall=wall,
        clearance=CL,
        min_strut=profile.MIN_STRUT,
        curvature=surface.min_curvature_radius(),
    )
    seam_solid = max(p.seam_solid_width, spec.solid_floor)
    limits["seam_solid_width"] = (spec.solid_floor, TF_RANGES["seam_solid_width"].hi)
    if seam_solid > p.seam_solid_width + 1e-6:
        notes.append(f"Seam band widened to {seam_solid:.1f} mm to cover the magnets")

    layout = Layout.build(
        surface, p.surface_smoothing, max(wall, spec.shelf_bottom), p.seam_offset, CL, res, wall
    )
    limits["seam_offset"] = (0.0, layout.seam_offset_max)
    if layout.seam_offset < p.seam_offset - 1e-6:
        notes.append(f"Seams held {layout.seam_offset:.1f} mm back to keep the back half a quarter turn")

    pylon = mt.Pylon.for_surface(surface, layout.knee.axis_y)
    lower_shape = mt.ClampShape("round", p.lower_hole_diameter / 2.0, p.lower_hole_diameter / 2.0, p.bolt_diameter, profile.MIN_STRUT, CL)
    upper_shape = mt.ClampShape("rect", p.upper_hole_width / 2.0, p.upper_hole_depth / 2.0, p.bolt_diameter, profile.MIN_STRUT, CL)
    key = (
        round(p.surface_smoothing, 4),
        round(wall, 3),
        round(layout.seam_offset, 2),
        round(p.magnet_diameter, 2),
        round(p.magnet_height, 2),
        res,
    )
    # Clamps first: they are bound to the hardware. Magnets then find room
    # along the seams around the breaks the clamps leave in the shelves.
    plans = {
        "lower": _plan("lower", lower_shape, p.lower_clamp_z, layout, spec, pylon, profile, {}, key),
        "upper": _plan("upper", upper_shape, p.upper_clamp_z, layout, spec, pylon, profile, {}, key),
    }
    gaps = mt.shelf_gaps(plans.values(), CL)
    sites = mt.magnet_sites(layout, spec, gaps, pylon)
    placed = sum(len(v) for v in sites.values())
    if placed < 2 * spec.count:
        notes.append(f"{placed} magnets placed of {2 * spec.count}")
    for name, plan in plans.items():
        limits[f"{name}_clamp_z"] = (plan.lo, plan.hi)
        notes.extend(plan.notes)
        wanted = p.lower_clamp_z if name == "lower" else p.upper_clamp_z
        if plan.ring > 0 and abs(plan.z - wanted) > 0.5:
            notes.append(f"{name.capitalize()} clamp moved to {plan.z:.0f} mm, where it fits")

    clamp_parts = {name: mt.clamp_bodies(plan, profile) for name, plan in plans.items()}
    feet = [f for _, _, fs in clamp_parts.values() for f in fs]
    rib_width = max([plan.rib_width for plan in plans.values()] + [0.0])

    # --- the edges, as a mask and as a keep-out ------------------------------
    uu, vv = np.meshgrid(layout.u, layout.v)
    z = surface.z_of_v(vv)
    rim = np.minimum(z - surface.z0, surface.z1 - z)
    seam_d = layout.seam_distance()
    fade = (
        _smoothstep((rim - RIM_SOLID) / EDGE_FADE)
        * _smoothstep((seam_d - seam_solid) / EDGE_FADE)
        * _smoothstep(layout.notch / NOTCH_FADE)
    )
    keep = np.minimum(np.minimum(rim - RIM_SOLID, seam_d - seam_solid), layout.notch - strut)
    if feet:
        pts = surface.point(uu, np.clip(vv, 0.0, 1.0))
        foot_d = np.full(uu.shape, np.inf)
        for f in feet:
            foot_d = np.minimum(foot_d, np.linalg.norm(pts - f, axis=-1))
        reach = rib_width / 2.0 + strut
        fade = fade * _smoothstep((foot_d - reach) / EDGE_FADE)
        keep = np.minimum(keep, foot_d - reach)
    edge_mask = layout.interpolator(fade)
    keep_at = layout.interpolator(keep)
    design_mask = as_array_field(mask_from(p))

    def mask(u, v):
        return design_mask(u, v) * np.clip(edge_mask(u, v), 0.0, 1.0)

    # --- the pattern ---------------------------------------------------------
    rings = {"front": [], "back": []}
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
    seam_at = layout.interpolator(layout.seam)
    holes = 0
    if p.operation == "cut":
        chord_tolerance = 0.05 * strut
        placement = _placement(p)
        if placement is not None:
            notes.extend(mo.resolve(p).notes)
        pattern = build_pattern(
            cells,
            mask,
            profile=profile,
            corner_radius=p.corner_radius,
            quad_segs=quality.quad_segs,
            chord_tolerance=chord_tolerance,
            placement=placement,
        )
        dropped = 0
        for ring in pattern.holes:
            dense = _densify_uv(ring, 8)
            if np.min(keep_at(dense[:, 0], dense[:, 1])) < KEEP_MARGIN:
                dropped += 1
                continue
            c = ring.mean(axis=0)
            width, length = _hole_size(ring, c, layout)
            strength = float(edge_mask(c[0], c[1]))
            faded = strength < 0.999
            if strength < FADE_KEEP or width < MIN_TIDY_HOLE or (faded and width < TIDY_ASPECT * length):
                dropped += 1
                continue
            rings["front" if seam_at(c[0], c[1]) > 0 else "back"].append(ring)
        if p.back_leaves:
            from . import leaves as lv

            spec_leaf = lv.LeafSpec(
                count=int(round(p.leaf_count)),
                length=p.leaf_size,
                tilt=p.leaf_tilt,
                strut=strut,
                a_max=cells.a_max,
                profile=profile,
            )
            back_at = layout.interpolator(layout.back_field())
            leaf_rings, leaf_notes = lv.place(spec_leaf, layout, keep_at, back_at)
            # The leaves are the back half's pattern: cells there would only
            # blur them.
            rings["back"] = leaf_rings
            notes.extend(leaf_notes)
        holes = len(rings["front"]) + len(rings["back"])
        if pattern.subdivided:
            notes.append(f"Pattern refined across {pattern.subdivided} cells for stiffness")
        if dropped:
            notes.append(f"{dropped} cells at the edges left solid")
        if p.hole_shape == "image" and placement is None:
            notes.append("No picture held, cells used")
    elif p.operation == "none":
        notes.append("Smooth shell, no pattern")

    outer = 0.0
    if p.has_relief and cells is not None:
        sign = 1.0 if p.operation == "emboss" else -1.0

        def outer(uv):
            h = rl.height_field(cells, mask, uv[:, 0], uv[:, 1], depth=depth, profile=p.relief_profile, length=surface.length)
            return sign * h

    # --- bodies ----------------------------------------------------------------
    chord = res.chord
    thinnest = float(np.min(surface.semi_axes(np.linspace(0.0, 1.0, 64))[0]))
    max_clear = 0.3 * max(thinnest - wall, 1.0)
    curvature = surface.min_curvature_radius()

    def shell(field_grid, centre_u, owner) -> tuple[Manifold, float]:
        region = layout.region(field_grid, centre_u)
        parts, plain = [], []
        for poly in region.geoms:
            body = mb.slab(surface, poly, outer, -wall, chord)
            if body is None:
                continue
            parts.append(mb.to_manifold(body))
            flat = body if outer == 0.0 else mb.slab(surface, poly, 0.0, -wall, chord)
            plain.append(abs(float(flat.volume)))
        solid = Manifold.batch_boolean(parts, OpType.Add) if len(parts) > 1 else parts[0]
        prisms = mb.hole_prisms(surface, rings[owner], wall, curvature, max_clear, 0.05 * strut) if rings[owner] else None
        if prisms is not None:
            solid = Manifold.batch_boolean([solid, mb.to_manifold(prisms)], OpType.Subtract)
        return solid, sum(plain)

    front, front_plain = shell(layout.front_field(), 0.25, "front")
    back, back_plain = shell(layout.back_field(), 0.75, "back")

    # Shelves run the length of a seam and the leg narrows at the ankle: where
    # the tube comes close, a shelf stops short of it.
    shelf = mt.shelves(layout, spec, min(chord, 2.5), gaps, pylon)
    pad = mt.pads(layout, spec, sites, min(chord, 2.0))
    back_sockets, front_sockets = mt.sockets(spec, sites)
    front_add = [front, *shelf] + [parts[0] for parts in clamp_parts.values() if parts[0] is not None]
    front = Manifold.batch_boolean(front_add, OpType.Add)
    if front_sockets:
        front = Manifold.batch_boolean([front, *front_sockets], OpType.Subtract)
    back = Manifold.batch_boolean([back, *pad], OpType.Add) if pad else back
    if back_sockets:
        back = Manifold.batch_boolean([back, *back_sockets], OpType.Subtract)

    bodies_m = {"front": _trim(front, surface), "back": _trim(back, surface)}
    for name, (_, back_part, _) in clamp_parts.items():
        if back_part is not None:
            bodies_m[f"{name}_clamp_back"] = back_part

    bodies = {k: _largest(mb.from_manifold(v)) for k, v in bodies_m.items()}
    density = p.material_spec.density
    volumes = {k: float(m.volume) for k, m in bodies.items()}
    masses = {k: v / 1000.0 * density for k, v in volumes.items()}
    extras = sum(v for k, v in volumes.items()) - volumes["front"] - volumes["back"]
    shelf_volume = sum(s.volume() for s in shelf) + sum(x.volume() for x in pad)
    plain = (front_plain + back_plain + shelf_volume + max(extras, 0.0)) / 1000.0 * density
    # Clamp front parts live inside the front half; count them in the plain
    # reference too, so the balance compares like with like.
    plain += sum(
        parts[0].volume() for parts in clamp_parts.values() if parts[0] is not None
    ) / 1000.0 * density

    return TFCover(
        params=p,
        profile=profile,
        bodies=bodies,
        volumes=volumes,
        masses=masses,
        mass_g=sum(masses.values()),
        plain_mass_g=plain,
        holes=holes,
        notes=notes,
        limits=limits,
        wall=wall,
        strut=strut,
        max_wall=max_wall,
        max_relief=max_relief,
        layout=layout,
        magnets=sites,
        spec=spec,
        plans=plans,
        pylon=pylon,
        rings=rings,
        keep=keep_at,
    )


def _placement(p: TFParams) -> Placement | None:
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


def _hole_size(ring: np.ndarray, centre: np.ndarray, layout: Layout) -> tuple[float, float]:
    """Width and length of a hole, mm: the widest circle it holds, and the
    longer side of the smallest box around it.

    The ring is in (u, v); one unit of either is worth a different number of
    millimetres and that changes along the leg, so it is measured at the
    hole's own place on the surface.
    """
    su, sv = layout.uv_mm(float(centre[0]), float(centre[1]))
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


def _densify_uv(ring: np.ndarray, per_edge: int) -> np.ndarray:
    nxt = np.roll(ring, -1, axis=0)
    t = np.linspace(0.0, 1.0, per_edge, endpoint=False)[None, :, None]
    return (ring[:, None, :] * (1 - t) + nxt[:, None, :] * t).reshape(-1, 2)


def _trim(body: Manifold, surface: ScanSurface) -> Manifold:
    """Nothing above the top of the kneecap, nothing below the scan."""
    body = body.trim_by_plane([0.0, 0.0, -1.0], -cfg.top_z)
    return body.trim_by_plane([0.0, 0.0, 1.0], surface.z0)


def _largest(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """One body. A sliver a boolean shed belongs to nothing and is dropped."""
    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh
    return max(parts, key=lambda m: abs(m.volume))


def audit(cover: TFCover) -> list[str]:
    faults = []
    for name, m in cover.bodies.items():
        if not m.is_watertight:
            faults.append(f"{name}: not watertight")
        if not m.is_winding_consistent:
            faults.append(f"{name}: winding not consistent")
        if m.volume <= 0:
            faults.append(f"{name}: volume is not positive")
        if m.body_count != 1:
            faults.append(f"{name}: {m.body_count} bodies")
    if faults:
        log.error("transfemoral generator produced (%s) for params=%r", "; ".join(faults), cover.params.to_dict())
    return faults
