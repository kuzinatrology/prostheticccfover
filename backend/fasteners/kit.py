"""Put a cover on the prosthesis: one call, from a finished cover to bodies.

Takes the cover a tab has already built -- shape, wall, pattern and all -- and
gives back the four bodies that go to the printer:

    front               the front half, with the land, the tongue, the magnet
                        pockets, and the front part and web of every clamp
    back                the back half, with the land, the groove and its
                        magnet pockets
    <name>_clamp_back   one per clamp: the strap that closes round the tube

Nothing here knows which cover it is holding.  Both tabs that use it store
their shape the same way and both are drawn about a centre line, which is all
the seam and the web ask of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from manifold3d import Manifold

from ..printer_profile import DEFAULT_PROFILE, PrinterProfile
from . import clamp as cl
from . import config as cfg
from . import notch as nt
from . import seam as sm
from . import solids as S
from .hardware import Hardware


@dataclass
class FastenerParams:
    magnet_count: int = 5
    magnet_diameter: float = 4.0
    magnet_height: float = 3.0
    bolt_diameter: float = 4.0
    seam_curve: float = cfg.SEAM_CURVE
    free_lower: bool = False
    """Leave the lower clamp loose instead of webbing it to the front half.

    Off: it holds the cover like the upper one does.  On, it grips the pylon
    and the cover sits round it with a fitting gap -- a steady, not a fixing,
    which is not enough on its own."""
    flexion: float = cfg.FLEXION_ANGLE
    tidy_top: bool = True
    """Trim the top to one smooth curve instead of the edge the sweep leaves.

    The raw edge is uneven -- on this cover it drops twenty millimetres over
    part of the front, because at no flexion at all the thigh stands straight
    up through the top of it.  Trimming costs a little height and buys a rim
    that reads as a line rather than as a bite."""
    nut_kind: str = "heat_set"
    lower_clamp_z: float = -1e9
    upper_clamp_z: float = -1e9
    clamps: int = 2

    def bolt(self) -> cl.Bolt:
        kind = self.nut_kind if self.nut_kind in cfg.NUT_KINDS else "heat_set"
        return cl.Bolt(self.bolt_diameter, kind)


@dataclass
class Kit:
    bodies: dict[str, Manifold]
    seam: sm.SeamPlan
    clamps: list[cl.ClampPlan]
    sweep: object = None
    cut: Manifold | None = None
    """The notch and the trimmed top as one solid, kept so a tab that rebuilds
    the cover at another size can take the same shape out of it."""

    clamp_parts: dict = field(default_factory=dict)
    """Every clamp body, including the front part of a webbed clamp -- which
    is fused into the front half here, but is its own piece for a tab that
    stands the hardware beside the cover."""
    limits: dict[str, tuple[float, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def solid_bands(self) -> list[tuple[float, float]]:
        """Heights the pattern has to leave solid, so a web lands on wall."""
        return [p.band for p in self.clamps]


def default_heights(hardware: Hardware, count: int) -> list[float]:
    """Where clamps go when nobody has said: spread over the tube.

    Spread and not stacked: two clamps hold the cover's tilt in proportion to
    how far apart they are, and the tube is the only stretch of the prosthesis
    that is a known circle in a known place.
    """
    lo, hi = hardware.clamp_band
    if count <= 1:
        return [0.5 * (lo + hi)]
    return list(np.linspace(lo, hi, count))


def plan(surface, wall: float, hardware: Hardware, params: FastenerParams,
         profile: PrinterProfile = DEFAULT_PROFILE, rows: int = 240):
    """Settle the seam and the clamps, before anything is built.

    Kept apart from `build` because the pattern has to know the answer first:
    a hole under the land or under a web is a hole in the part that holds the
    cover on, so the tab plans, patterns around the plan, and only then builds.
    """
    clearance = profile.CLEARANCE
    notes: list[str] = []
    bolt = params.bolt()

    # The seam's curve first: a clamp's lugs straddle it and both its parts are
    # cut by it, so nothing about a clamp can be settled until it is known.
    curve = sm.seam_curve(surface, params.seam_curve)

    wanted = default_heights(hardware, params.clamps)
    given = [params.lower_clamp_z, params.upper_clamp_z]
    for i in range(min(len(wanted), len(given))):
        if given[i] > -1e8:
            wanted[i] = given[i]
    plans: list[cl.ClampPlan] = []
    for name, z in zip(("lower", "upper", "third"), wanted):
        # Every clamp carries a web.  A ring that grips only the tube steadies
        # the cover and holds nothing: what holds it is the web, which is a
        # wall of the front half.  Two webs on one straight tube still press
        # on together, so there is nothing to thread.
        plans.append(cl.plan(name, z, hardware, curve, bolt, [q.z for q in plans],
                             surface=surface, wall=wall, clearance=clearance,
                             free=params.free_lower and name == "lower"))
        notes.extend(plans[-1].notes)
    placed = [q for q in plans if q.placed]

    seam_plan = sm.plan(
        surface, hardware, wall, params.magnet_count, clearance,
        params.magnet_diameter, params.magnet_height, rows=rows,
        # A free clamp is not fused to either half, so it takes nothing from
        # the seam and a magnet may sit level with it.
        avoid=[q.band for q in placed if not q.free], curve=curve,
    )
    notes.extend(seam_plan.notes)
    sweep = nt.Sweep.for_cover(hardware, params.flexion)
    return seam_plan, placed, notes, sweep


def solid_field(surface, seam_plan: sm.SeamPlan, clamps: list[cl.ClampPlan], sweep=None):
    """How far a point on the surface is from anything that must stay solid.

    Millimetres, negative inside.  Two things: the band along the seam, wide
    enough to cover the land, and a band at each clamp, tall enough to cover
    the web and the taper it lands on.
    """
    band = cfg.LAND_HALF_WIDTH + 2.0
    # A free clamp touches nothing, so it asks nothing of the pattern.
    bands = [q.band for q in clamps if not q.free]

    def field(u, v):
        p = surface.point(u, v)
        d = np.abs(p[..., 1] - seam_plan.y_at(p[..., 2])) - band
        z = p[..., 2]
        for lo, hi in bands:
            mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0
            d = np.minimum(d, np.abs(z - mid) - half)
        if sweep is not None:
            # The notch is an edge like any other, but a wider one: it is the
            # edge people look at, and the transfemoral tab fades it over 35 mm
            # rather than 14 for that reason.
            hole = sweep.distance(p.reshape(-1, 3)).reshape(np.shape(p)[:-1])
            d = np.minimum(d, (hole - cfg.NOTCH_CLEARANCE) * cfg.SEAM_FADE / cfg.NOTCH_FADE)
        return d

    return field


def edge_field(surface, seam_plan: sm.SeamPlan, clamps: list[cl.ClampPlan], sweep=None):
    """Distance to every edge a large motif has to keep off, in millimetres.

    Not `solid_field`: that one is scaled, because it feeds a fade whose own
    width is fixed and the notch fades over a wider band than a rim does.  A
    leaf being fitted wants the true distance, and scaling it by two and a half
    is why the leaves came out shrunk to a third and half of them dropped.
    """
    band = cfg.LAND_HALF_WIDTH + 2.0
    bands = [q.band for q in clamps if not q.free]

    def field(u, v):
        p = surface.point(u, v)
        d = np.abs(p[..., 1] - seam_plan.y_at(p[..., 2])) - band
        z = p[..., 2]
        for lo, hi in bands:
            mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0
            d = np.minimum(d, np.abs(z - mid) - half)
        if sweep is not None:
            hole = sweep.distance(p.reshape(-1, 3)).reshape(np.shape(p)[:-1])
            d = np.minimum(d, hole - cfg.NOTCH_CLEARANCE)
        return d

    return field


def build(cover: Manifold, surface, wall: float, hardware: Hardware,
          params: FastenerParams, profile: PrinterProfile = DEFAULT_PROFILE,
          rows: int = 240, plans=None) -> Kit:
    clearance = profile.CLEARANCE
    seam_plan, placed, notes, sweep = plans if plans is not None else plan(
        surface, wall, hardware, params, profile, rows)

    # The notch is taken out twice: once from the cover, so the land and the
    # magnets are placed on a shape that already has its opening, and once
    # from each finished half.  The second time is what matters -- the land,
    # the tongue and the bosses are added after the first cut and would
    # otherwise fill the opening back in along the seam.
    cut = sweep.solid(grow=cfg.NOTCH_CLEARANCE)
    if params.tidy_top:
        lo, hi = sm._height_range(surface)
        top_centre = S.centre_of(surface, np.array([hi]))[0]
        theta, z_rim = nt.tidy_top(surface, sweep, cfg.NOTCH_CLEARANCE, centre=top_centre)
        cut = S.add([cut, S.roof(top_centre, theta, z_rim)])
    cover = S.sub(cover, [cut])

    core = S.core(surface, wall - cfg.OVERLAP, rows=rows)
    land = sm.land(surface, wall, seam_plan)
    tongue = sm.tongue(surface, wall, seam_plan, 0.0, clearance / 2.0, params.magnet_diameter)
    groove = sm.tongue(surface, wall, seam_plan, clearance, clearance / 2.0, params.magnet_diameter)

    curve = (seam_plan.z_curve, seam_plan.y_curve)
    fronts, loose, bosses, clamp_parts = [], {}, [], {}
    for q in placed:
        f, b, boss = cl.bodies(surface, wall, q, core, curve, clearance)
        if q.free:
            # Neither part belongs to the cover: both are their own bodies and
            # nothing is added to the shell, not even a boss.
            loose[f"{q.name}_clamp_front"] = f
            loose[f"{q.name}_clamp_back"] = b
        else:
            fronts.append(f)
            loose[f"{q.name}_clamp_back"] = b
            bosses.append(boss)
        clamp_parts[f"{q.name}_clamp_front"] = f
        clamp_parts[f"{q.name}_clamp_back"] = b

    whole = S.add([cover, land, *bosses])
    front_space = S.curved_half(*curve, +1, clearance / 2.0)
    back_space = S.curved_half(*curve, -1, clearance / 2.0)

    front = S.add([whole ^ front_space, *([tongue] if tongue else []), *fronts])
    back = whole ^ back_space
    if groove is not None:
        back = S.sub(back, [groove])

    front = S.sub(front, sm.magnet_pockets(
        surface, wall, seam_plan, params.magnet_diameter, params.magnet_height, clearance, +1))
    back = S.sub(back, sm.magnet_pockets(
        surface, wall, seam_plan, params.magnet_diameter, params.magnet_height, clearance, -1))

    front = S.sub(front, [cut])
    back = S.sub(back, [cut])
    bodies = {"front": _largest(front), "back": _largest(back)}
    bodies.update({k: v for k, v in loose.items() if v.volume() > 1.0})
    limits = {f"{q.name}_clamp_z": (q.lo, q.hi) for q in placed}
    return Kit(bodies=bodies, seam=seam_plan, clamps=placed, limits=limits,
               notes=notes, sweep=sweep, cut=cut, clamp_parts=clamp_parts)


def _largest(body: Manifold) -> Manifold:
    """A plane through a lattice can lift a strut junction clear of both halves.

    Keeping only the biggest piece is what the old split did and it is still
    right: the crumb is a strut end, not a part.
    """
    parts = body.decompose()
    return body if len(parts) <= 1 else max(parts, key=lambda m: m.volume())
