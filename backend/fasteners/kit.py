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
from . import seam as sm
from . import solids as S
from .hardware import Hardware


@dataclass
class FastenerParams:
    magnet_count: int = 5
    magnet_diameter: float = 6.0
    magnet_height: float = 3.0
    bolt_diameter: float = 4.0
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

    # The seam's plane first: a clamp's lugs straddle it, so they cannot be
    # placed until it is known, and it costs one pass over the centre line.
    y = sm.seam_y(surface)

    wanted = default_heights(hardware, params.clamps)
    given = [params.lower_clamp_z, params.upper_clamp_z]
    for i in range(min(len(wanted), len(given))):
        if given[i] > -1e8:
            wanted[i] = given[i]
    plans: list[cl.ClampPlan] = []
    for name, z in zip(("lower", "upper", "third"), wanted):
        plans.append(cl.plan(name, z, hardware, y, bolt, [q.z for q in plans],
                             surface=surface, wall=wall, clearance=clearance))
        notes.extend(plans[-1].notes)
    placed = [q for q in plans if q.placed]

    seam_plan = sm.plan(
        surface, hardware, wall, params.magnet_count, clearance,
        params.magnet_diameter, params.magnet_height, rows=rows,
        avoid=[q.band for q in placed],
    )
    notes.extend(seam_plan.notes)
    return seam_plan, placed, notes


def solid_field(surface, seam_plan: sm.SeamPlan, clamps: list[cl.ClampPlan]):
    """How far a point on the surface is from anything that must stay solid.

    Millimetres, negative inside.  Two things: the band along the seam, wide
    enough to cover the land, and a band at each clamp, tall enough to cover
    the web and the taper it lands on.
    """
    band = cfg.LAND_HALF_WIDTH + 2.0
    bands = [q.band for q in clamps]

    def field(u, v):
        p = surface.point(u, v)
        d = np.abs(p[..., 1] - seam_plan.y) - band
        z = p[..., 2]
        for lo, hi in bands:
            mid, half = (lo + hi) / 2.0, (hi - lo) / 2.0
            d = np.minimum(d, np.abs(z - mid) - half)
        return d

    return field


def build(cover: Manifold, surface, wall: float, hardware: Hardware,
          params: FastenerParams, profile: PrinterProfile = DEFAULT_PROFILE,
          rows: int = 240, plans=None) -> Kit:
    clearance = profile.CLEARANCE
    seam_plan, placed, notes = plans if plans is not None else plan(
        surface, wall, hardware, params, profile, rows)

    core = S.core(surface, wall - cfg.OVERLAP, rows=rows)
    land = sm.land(surface, wall, seam_plan)
    tongue = sm.tongue(surface, wall, seam_plan, 0.0, clearance / 2.0, params.magnet_diameter)
    groove = sm.tongue(surface, wall, seam_plan, clearance, clearance / 2.0, params.magnet_diameter)

    fronts, backs, bosses = [], {}, []
    for q in placed:
        f, b, boss = cl.bodies(surface, wall, q, core, seam_plan.y, clearance)
        fronts.append(f)
        backs[f"{q.name}_clamp_back"] = b
        bosses.append(boss)

    whole = S.add([cover, land, *bosses])
    half = 450.0
    front_space = S.slab([0.0, seam_plan.y + half + clearance / 2.0, 0.0], "y", half)
    back_space = S.slab([0.0, seam_plan.y - half - clearance / 2.0, 0.0], "y", half)

    front = S.add([whole ^ front_space, *([tongue] if tongue else []), *fronts])
    back = whole ^ back_space
    if groove is not None:
        back = S.sub(back, [groove])

    front = S.sub(front, sm.magnet_pockets(
        surface, wall, seam_plan, params.magnet_diameter, params.magnet_height, clearance, +1))
    back = S.sub(back, sm.magnet_pockets(
        surface, wall, seam_plan, params.magnet_diameter, params.magnet_height, clearance, -1))

    bodies = {"front": _largest(front), "back": _largest(back)}
    bodies.update({k: v for k, v in backs.items() if v.volume() > 1.0})
    limits = {f"{q.name}_clamp_z": (q.lo, q.hi) for q in placed}
    return Kit(bodies=bodies, seam=seam_plan, clamps=placed, limits=limits, notes=notes)


def _largest(body: Manifold) -> Manifold:
    """A plane through a lattice can lift a strut junction clear of both halves.

    Keeping only the biggest piece is what the old split did and it is still
    right: the crumb is a strut end, not a part.
    """
    parts = body.decompose()
    return body if len(parts) <= 1 else max(parts, key=lambda m: m.volume())
