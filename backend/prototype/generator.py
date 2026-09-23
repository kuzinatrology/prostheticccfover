"""The prototype: the Iteration 2 cover, smaller, with its hardware beside it.

Built in two passes.  The first is the cover exactly as the tab shows it, at
full size -- that pass is what settles the design: which holes, where the seam
runs, where the clamps sit, how far the notch reaches.  The second lays that
same design on a surface shrunk to `scale`, and everything it asks for there
it asks for in millimetres, so the wall, the land and the magnet seats come
out the size they will really be printed at.

The holes carry over untouched.  A hole is a ring in the surface's own (u, v)
coordinates and those do not know how big the surface is, so the pattern lands
exactly where it landed before -- the drawing is the same drawing, smaller.

The clamps do not shrink and are not inside anything: they stand beside the
cover at full size, which is the only way to see them at all once the cover
they belong in is too small to hold a 34 mm tube.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh
from manifold3d import Manifold

from .. import mesh_build as mb
from ..fasteners import clamp as cl
from ..fasteners import config as fc
from ..fasteners import kit as fkit
from ..fasteners import seam as sm
from ..fasteners import solids as S
from ..fasteners.hardware import Hardware
from ..fasteners.scaled import ScaledSurface
from ..iteration1.generator import DRAFT, FINAL, Quality
from ..iteration1.surface import IterSurface
from ..iteration2.generator import Iter2Cover
from ..iteration2.generator import generate as build_full
from ..printer_profile import DEFAULT_PROFILE, PrinterProfile
from .params import ProtoParams

BODY_NAMES = ("front", "back",
              "lower_clamp_front", "lower_clamp_back",
              "upper_clamp_front", "upper_clamp_back")

__all__ = ["DRAFT", "FINAL", "generate", "audit", "BODY_NAMES", "ProtoCover"]


@dataclass
class ProtoCover(Iter2Cover):
    scale: float = 1.0
    full: Iter2Cover | None = field(repr=False, default=None)


def _scaled_seam(plan: sm.SeamPlan, factor: float) -> sm.SeamPlan:
    """The same seam on the smaller cover: its line shrinks, its land does not.

    The curve and the magnet heights are places on the cover, so they scale
    with it and the seam stays the same line.  `depth_v` is a thickness in
    millimetres and stays as it is, which is what keeps a 4 mm magnet seat a
    4 mm magnet seat.
    """
    return sm.SeamPlan(
        z_curve=plan.z_curve * factor,
        y_curve=plan.y_curve * factor,
        depth_v=plan.depth_v.copy(),
        z_of_v=plan.z_of_v * factor,
        z_lo=plan.z_lo * factor,
        z_hi=plan.z_hi * factor,
        magnets=[z * factor for z in plan.magnets],
        notes=[],
    )


def _beside(bodies: dict[str, Manifold], reach: float, gap: float,
            factor: float) -> dict[str, Manifold]:
    """Stand the loose parts in a row beside the cover, at full size.

    Sideways they go in the order they sit on the leg; in height each one is
    put where it belongs on the shrunken cover, so it is still clear which
    clamp is which and where each one grips, even though neither is inside
    anything any more.
    """
    out: dict[str, Manifold] = {}
    x = reach + gap
    for name in BODY_NAMES[2:]:
        body = bodies.get(name)
        if body is None:
            continue
        lo, hi = np.array(body.bounding_box(), dtype=float).reshape(2, 3)
        mid_z = (lo[2] + hi[2]) / 2.0
        out[name] = body.translate([float(x - lo[0]), 0.0, float(mid_z * factor - mid_z)])
        x += (hi[0] - lo[0]) + gap
    return out


def generate(
    params: ProtoParams,
    *,
    quality: Quality = FINAL,
    profile: PrinterProfile = DEFAULT_PROFILE,
) -> ProtoCover:
    p = params.clamped()
    factor = p.scale

    full = build_full(p, quality=quality, profile=profile)
    base: IterSurface = full.surface
    surface = ScaledSurface(base, factor)
    wall = full.wall
    clearance = profile.CLEARANCE
    rows = 160 if quality is DRAFT else 240

    # --- the cover, small, with the same holes in it -----------------------
    from ..iteration1 import mesh as im

    grid = surface.loft_grid(quality.rows)
    cover = im.shell(grid, surface.offset_grid(grid, -wall))
    if full.rings:
        v = np.linspace(0.0, 1.0, 64)
        thinnest = float(np.min(surface.semi_axes(v)[0]))
        prisms = mb.hole_prisms(
            surface, full.rings, wall, surface.min_curvature_radius(),
            max_clear=0.3 * max(thinnest - wall, 1.0),
            chord_tolerance=quality.chord_tolerance * max(p.strut_width, profile.MIN_STRUT),
        )
        cover = mb.perforate(cover, prisms)

    # --- the notch and the trimmed top, shrunk with the shape --------------
    # Taken from the full-size build rather than solved again: the thigh is a
    # real thigh and would swallow a cover this size whole.
    seam_plan = _scaled_seam(full.seam, factor)
    sweep = full.sweep_solid
    cut = None if sweep is None else sweep.scale([factor, factor, factor])
    if cut is not None:
        cover = S.sub(cover, [cut])

    # --- the seam, its land and its magnets, all in millimetres ------------
    land = sm.land(surface, wall, seam_plan)
    tongue = sm.tongue(surface, wall, seam_plan, 0.0, clearance / 2.0, p.magnet_diameter)
    groove = sm.tongue(surface, wall, seam_plan, clearance, clearance / 2.0, p.magnet_diameter)
    curve = (seam_plan.z_curve, seam_plan.y_curve)

    # --- the clamps, twice over -------------------------------------------
    #
    # A clamp is the size it is: it grips a real 34 mm tube with real bolts,
    # and at this scale it is wider than the cover's own section, so the
    # printed parts are the full-size ones and they stand beside the cover.
    #
    # But a part standing beside it does not show how it sits.  So the web of
    # the clamp that belongs to the front half goes in as well, shrunk by the
    # same factor about the same point -- which puts it exactly where it was,
    # against a wall that moved exactly as far.  It is a picture of the
    # arrangement, not a part: its bore is 0.6 of a pylon and nothing fits it.
    loose = dict(full.loose_clamps)
    fused = []
    notes_c = []
    for q in full.clamps:
        if q.free:
            continue
        web = loose.get(f"{q.name}_clamp_front")
        if web is not None:
            fused.append(web.scale([factor, factor, factor]))
            notes_c.append(
                f"The {q.name} clamp's web is in the cover at {factor:.2f} of size, "
                "and beside it at full size as the part to print"
            )

    whole = S.add([cover, *( [land] if land is not None else [] ), *fused])
    front = whole ^ S.curved_half(*curve, +1, clearance / 2.0)
    back = whole ^ S.curved_half(*curve, -1, clearance / 2.0)
    if tongue is not None:
        front = S.add([front, tongue])
    if groove is not None:
        back = S.sub(back, [groove])
    front = S.sub(front, sm.magnet_pockets(
        surface, wall, seam_plan, p.magnet_diameter, p.magnet_height, clearance, +1))
    back = S.sub(back, sm.magnet_pockets(
        surface, wall, seam_plan, p.magnet_diameter, p.magnet_height, clearance, -1))

    # And again, on the finished halves.  The land, the tongue and the clamps
    # are added after the first cut and would otherwise fill the opening back
    # in and stand up past the trimmed rim -- which is exactly what they did.
    if cut is not None:
        front = S.sub(front, [cut])
        back = S.sub(back, [cut])

    lo, hi = np.array(cover.bounding_box(), dtype=float).reshape(2, 3)
    parts = {"front": fkit._largest(front), "back": fkit._largest(back)}
    parts.update(_beside(loose, float(hi[0]), p.beside_gap, 1.0))

    density = p.material_spec.density
    bodies = {k: mb.from_manifold(v_) for k, v_ in parts.items()}
    volumes = {k: float(m.volume) for k, m in bodies.items()}
    masses = {k: v_ / 1000.0 * density for k, v_ in volumes.items()}
    notes = [
        f"Cover at {factor:.2f} of size; wall, land, magnet seats and clamps left as they are",
        *notes_c,
        *full.notes,
    ]
    return ProtoCover(
        bodies=bodies, params=p, profile=profile, volumes=volumes, masses=masses,
        mass_g=sum(masses.values()), plain_mass_g=full.plain_mass_g,
        saving_pct=full.saving_pct, holes=len(full.rings), wall=wall,
        max_wall=full.max_wall, max_relief=full.max_relief, notes=notes,
        limits=full.limits, surface=base, seam=seam_plan, clamps=full.clamps,
        scale=factor, full=full,
    )


def audit(cover: ProtoCover) -> list[str]:
    faults = []
    for name, m in cover.bodies.items():
        if not m.is_watertight:
            faults.append(f"{name}: not closed")
        if m.body_count > 1:
            faults.append(f"{name}: {m.body_count} pieces")
    return faults
