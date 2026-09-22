"""Turn a set of parameters into a printable cover.

A design is four independent axes multiplied together:

    cell field  x  operation  x  mask  x  finish

Everything above the operation is shared. `cut` drives prisms through the wall
and removes them; `emboss` and `engrave` displace the outer surface and never
touch a boolean at all; `none` leaves it smooth. Finish is a property of the
preview and changes no geometry.

Nothing here can reject a design. When a limit binds, the generator absorbs it
and says so as a property of the object.

An uploaded picture is a fifth thing only in the sense that it replaces the
shape of a hole. It is resolved here, close to where the notes are written,
because what a picture cost the design is something the panel has to say.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import trimesh

from . import mesh_build as mb
from . import motif as mo
from . import relief as rl
from .fields import Field, Fields
from .params import RANGES, CoverParams
from .pattern import CellField, Placement, build_cells, build_pattern
from .printer_profile import DEFAULT_PROFILE, PrinterProfile
from .surface import Surface, SurfaceBase

log = logging.getLogger("cover")

CHORD_TOLERANCE = 0.05
"""How much of a strut a mesh edge may bow into, as a fraction of its width.

Long edges are split until they stay inside this, and the remainder is paid
back in the erosion. Lower is truer to the pattern and slower to build; this
costs the cover about a gram and keeps the strut honest."""


@dataclass
class Quality:
    nu: int
    nv: int
    quad_segs: int
    relief_nu: int
    relief_nv: int


# Relief is carried by the shell's own grid rather than by a boolean, so that
# grid has to resolve a cell rather than merely a section.
DRAFT = Quality(nu=64, nv=48, quad_segs=2, relief_nu=112, relief_nv=140)
FINAL = Quality(nu=128, nv=96, quad_segs=3, relief_nu=208, relief_nv=256)


@dataclass
class Cover:
    mesh: trimesh.Trimesh
    params: CoverParams
    profile: PrinterProfile

    volume_mm3: float = 0.0
    plain_volume_mm3: float = 0.0
    mass_g: float = 0.0
    plain_mass_g: float = 0.0
    saving_pct: float = 0.0
    """Positive when the pattern took material away, negative when relief
    added it."""

    holes: int = 0
    max_wall: float = 0.0
    max_relief: float = 0.0
    notes: list[str] = field(default_factory=list)
    components: int = 1
    cuts_through: bool = True


def generate(
    params: CoverParams,
    *,
    quality: Quality = FINAL,
    profile: PrinterProfile = DEFAULT_PROFILE,
    fields: Fields | None = None,
    surface: SurfaceBase | None = None,
    extra_holes=None,
) -> Cover:
    """`surface` overrides the analytic shin, which is how a cover whose shape
    is measured rather than drawn — the anatomic tab — gets the same four axes
    of pattern, mask, relief and finish without a second pipeline."""
    p = params.clamped()
    surface = surface if surface is not None else Surface.from_params(p)
    f = fields or Fields.from_params(p)
    notes: list[str] = []

    # Wall thickness: the slider's own ceiling moves with the surface, so a
    # thickness that would fold the inner offset is simply not reachable.
    max_wall = surface.max_wall_thickness(profile, RANGES["wall_thickness"].hi)
    wall = min(p.wall_thickness, max_wall)
    if wall < p.wall_thickness - 1e-6:
        notes.append(f"Wall held at {wall:.1f} mm by the curve of the leg")

    strut = max(p.strut_width, profile.MIN_STRUT)
    if p.cuts_through and strut > p.strut_width + 1e-6:
        notes.append(f"Struts widened to {strut:.1f} mm")

    max_relief = rl.max_depth(wall, p.operation == "engrave", RANGES["relief_depth"].hi)
    depth = min(p.relief_depth, max_relief)
    if p.has_relief and depth < p.relief_depth - 1e-6:
        notes.append(f"Relief held at {depth:.1f} mm by the wall")

    cells: CellField | None = None
    if p.operation != "none":
        cells = build_cells(
            surface,
            f.density,
            wall_thickness=wall,
            strut=strut,
            irregularity=p.irregularity,
            anisotropy=p.anisotropy,
            flow_angle=p.flow_angle,
            profile=profile,
            rng=np.random.default_rng(p.seed),
        )

    if p.operation == "cut":
        body, plain_volume, holes = _cut(
            p, f.mask, surface, cells, wall, strut, quality, profile, notes, extra_holes
        )
    elif p.has_relief:
        body, plain_volume = _relief(p, f.mask, surface, cells, wall, depth, quality)
        holes = 0
    else:
        plain = mb.shell(surface, wall, quality.nu, quality.nv)
        plain_volume = float(plain.volume)
        body = mb.to_manifold(plain)
        holes = 0
        notes.append("Smooth shell, no pattern")

    components = 1
    if p.split_halves:
        body = mb.split_halves(body, profile.CLEARANCE)
        components = 2
        notes.append(f"Split at the seam with a {profile.CLEARANCE:.1f} mm fit gap")

    mesh = mb.from_manifold(body)
    volume = float(mesh.volume)
    density = p.material_spec.density

    return Cover(
        mesh=mesh,
        params=p,
        profile=profile,
        volume_mm3=volume,
        plain_volume_mm3=plain_volume,
        mass_g=volume / 1000.0 * density,
        plain_mass_g=plain_volume / 1000.0 * density,
        saving_pct=100.0 * (1.0 - volume / plain_volume) if plain_volume > 0 else 0.0,
        holes=holes,
        max_wall=max_wall,
        max_relief=max_relief,
        notes=notes,
        components=components,
        cuts_through=p.cuts_through,
    )


def placement_for(p: CoverParams) -> Placement | None:
    """The motif a design asks for, ready to be laid into cells.

    Falls back to cells when the picture the design names is not one the
    session is still holding, which is what happens to a link opened later.
    """
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


def _cut(
    p: CoverParams,
    mask: Field,
    surface: Surface,
    cells: CellField,
    wall: float,
    strut: float,
    quality: Quality,
    profile: PrinterProfile,
    notes: list[str],
    extra_holes=None,
):
    # How far a mesh edge may bow into a strut. Paid back in the erosion, and
    # held down by splitting long edges, so the strut survives both.
    chord_tolerance = CHORD_TOLERANCE * strut
    placement = placement_for(p)
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
    if pattern.subdivided:
        notes.append(f"Pattern refined across {pattern.subdivided} cells for stiffness")
    if placement is not None:
        if pattern.thinned:
            notes.append(f"Thin details below {profile.MIN_HOLE:.1f} mm removed")
        if pattern.merged:
            notes.append(f"Details closer than {strut:.1f} mm merged")
        if pattern.reduced:
            notes.append(f"Motif reduced to {pattern.least_fill:.1f} in wide areas")
    if p.hole_shape == "image" and placement is None:
        notes.append("No picture held, cells used")

    rings = list(pattern.holes)
    if extra_holes is not None:
        # Large motifs the cell field would only blur. They come with the
        # ground they need: cells inside it come out, so the drawing reads
        # against solid wall instead of against more holes.
        added, added_notes, keepout = extra_holes(surface, cells, strut)
        notes.extend(added_notes)
        if added:
            if keepout is not None and rings:
                u_lo, u_hi, v_lo, v_hi = keepout
                centres = np.array([r.mean(axis=0) for r in rings])
                # u is periodic, so compare on the shortest way round.
                du = (centres[:, 0] - (u_lo + u_hi) / 2.0 + 0.5) % 1.0 - 0.5
                inside = (np.abs(du) < (u_hi - u_lo) / 2.0) & (centres[:, 1] > v_lo) & (centres[:, 1] < v_hi)
                rings = [r for r, hit in zip(rings, inside) if not hit]
            rings.extend(added)

    plain = mb.shell(surface, wall, quality.nu, quality.nv)
    # A prism must never be deep enough to touch the far side of the cover.
    v = np.linspace(0.0, 1.0, 64)
    thinnest = float(np.min(np.minimum(*surface.semi_axes(v))))
    prisms = mb.hole_prisms(
        surface,
        rings,
        wall,
        surface.min_curvature_radius(),
        max_clear=0.3 * max(thinnest - wall, 1.0),
        chord_tolerance=chord_tolerance,
    )
    return mb.perforate(plain, prisms), float(plain.volume), len(rings)


def _relief(
    p: CoverParams,
    mask: Field,
    surface: Surface,
    cells: CellField,
    wall: float,
    depth: float,
    quality: Quality,
):
    """Displace the outer surface. No holes, so no printability rules apply."""
    u = np.linspace(0.0, 1.0, quality.relief_nu, endpoint=False)
    v = np.linspace(0.0, 1.0, quality.relief_nv)
    uu, vv = np.meshgrid(u, v)
    point, normal = surface.frame(uu, vv)

    height = rl.height_field(
        cells, mask, uu, vv, depth=depth, profile=p.relief_profile, length=p.length
    )
    sign = 1.0 if p.operation == "emboss" else -1.0
    inner = point - normal * wall
    plain = mb.shell_from(point, inner)
    body = mb.shell_from(point + normal * (sign * height)[..., None], inner)
    return mb.to_manifold(body), float(plain.volume)


# --- the one check that exists, and it is on us, not the user ----------


def audit(cover: Cover) -> list[str]:
    """Full manifold check before anything leaves the building.

    A failure here is a generator bug. The user never sees it; the log does,
    with the parameters needed to reproduce it.
    """
    m = cover.mesh
    faults = []
    if not m.is_watertight:
        faults.append("not watertight")
    if not m.is_winding_consistent:
        faults.append("winding not consistent")
    if m.body_count != cover.components:
        faults.append(f"{m.body_count} bodies, expected {cover.components}")
    if m.volume <= 0:
        faults.append("volume is not positive")
    if not cover.cuts_through and cover.components == 1 and m.euler_number != 0:
        # A solid tube with two openings and nothing else: genus one.
        faults.append(f"euler number {m.euler_number}, expected 0")
    if faults:
        log.error(
            "generator produced an unprintable mesh (%s) for params=%r",
            ", ".join(faults),
            cover.params.to_dict(),
        )
    return faults
