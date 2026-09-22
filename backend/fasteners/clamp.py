"""A clamp: what actually holds the cover on the prosthesis.

The previous ones broke in the print, and the shape below is the answer to how.
They were a ring 2.4 to 6 mm thick and 10 mm tall, hung off the shell by two or
three ribs 5 mm wide -- cantilevers loaded in bending across the print's layers
with a square corner in the root, and `mounts._rib` stopped each rib as soon as
its end reached the inner face of the wall, so it butted against the shell
rather than merging into it.

This one is a **web**: the ring is joined to the shell by one continuous wall
running the entire arc of the front half, so a load arrives along the whole
section instead of through two points.  The web thickens where it meets the
ring and again where it meets the shell, because a mesh has no fillet operation
and a slab that grows toward both ends is the same thing where it matters.

The ring is still cut by the frontal plane and the back part is still its own
body, printed separately.  Its bolts pull it onto the tube against the front
part; they thread into brass inserts or captive nuts, never into the plastic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from manifold3d import CrossSection, Manifold

from . import config as cfg
from . import solids as S


@dataclass(frozen=True)
class Bolt:
    """A bolt and the thing it threads into."""

    diameter: float
    kind: str

    @property
    def head(self) -> tuple[float, float]:
        return cfg.SOCKET_HEAD[self._size]

    @property
    def _size(self) -> float:
        return min(cfg.BOLT_SIZES, key=lambda s: abs(s - self.diameter))

    @property
    def anchor_hole(self) -> float:
        """Diameter of what the front lug is bored for."""
        if self.kind == "heat_set":
            return cfg.HEAT_SET[self._size][0]
        return self.diameter + 0.4

    @property
    def anchor_depth(self) -> float:
        if self.kind == "heat_set":
            return cfg.HEAT_SET[self._size][1] + 1.0
        return cfg.HEX_NUT[self._size][1] + cfg.NUT_POCKET_CLEARANCE

    @property
    def lug_width(self) -> float:
        """Across the bolt: the widest of everything that has to fit round it."""
        return max(self.anchor_hole, self.head[0], self.diameter + 1.0) + 2.0 * cfg.LUG_STRUT

    @property
    def front_length(self) -> float:
        return self.anchor_depth + cfg.LUG_STRUT + (0.0 if self.kind == "heat_set" else 3.0)

    @property
    def back_length(self) -> float:
        return self.head[1] + cfg.LUG_STRUT + 1.0


@dataclass
class ClampPlan:
    name: str
    z: float
    bolt: Bolt
    bore: float
    ring: float
    height: float
    frame: np.ndarray
    seam_y: float
    lug_x: float
    lo: float
    hi: float
    placed: bool = True
    """False when there was nowhere to put it.

    A clamp that cannot be placed is left out rather than squeezed in: two
    clamps closer together than CLAMP_MIN_GAP overlap, and what comes back is
    one body with a tunnel through it, which is worse than one clamp."""

    notes: list[str] = field(default_factory=list)

    @property
    def band(self) -> tuple[float, float]:
        """Heights the shell has to keep solid for this clamp."""
        half = self.height / 2.0 + cfg.WEB_FLARE + 1.0
        return self.z - half, self.z + half


def room_at(surface, wall: float, hardware, seam_y: float, z: np.ndarray) -> np.ndarray:
    """Free radius from the tube's axis out to the cover's inner wall, at the
    seam, per height and side.

    This is what decides where a clamp can go.  Its lugs sit at the seam, which
    is where the ring's two ends are, and they reach further from the tube than
    anything else on the part; on the anatomic cover the seam leaves 12 mm at
    the ankle and 22 at the top of the tube, and an M4 lug wants 11.9.
    """
    from . import seam as sm

    z = np.atleast_1d(np.asarray(z, dtype=float))
    c = S.centre_of(surface, z)
    r = sm.seam_crossings(surface, seam_y, z)
    t = hardware.tube.centre(z)
    out = np.zeros((len(z), 2))
    for k, sign in enumerate((+1.0, -1.0)):
        good = np.isfinite(r[:, k])
        x = np.where(good, c[:, 0] + sign * np.sqrt(
            np.maximum(r[:, k] ** 2 - (seam_y - c[:, 1]) ** 2, 0.0)), np.nan)
        # Straight in along the section's own radius, which is how both covers
        # build their wall, so the inner face is `wall` nearer the centre.
        inner = np.where(good, np.abs(x - c[:, 0]) - wall, np.nan)
        px = c[:, 0] + sign * inner
        out[:, k] = np.where(good, np.hypot(px - t[:, 0], seam_y - t[:, 1]), 0.0)
    return out


def fits(surface, wall: float, hardware, seam_y: float, bolt: Bolt,
         z: float, clearance: float) -> bool:
    """Whether a clamp's lugs stay inside the cover at this height."""
    need = bolt_reach(hardware, bolt) + clearance
    room = room_at(surface, wall, hardware, seam_y, np.array([z]))[0]
    return bool(np.min(room) >= need)


def bolt_reach(hardware, bolt: Bolt) -> float:
    """How far a lug reaches from the tube's axis."""
    return (hardware.tube.radius + cfg.BORE_CLEARANCE + bolt.anchor_hole / 2.0
            + cfg.LUG_STRUT + bolt.lug_width / 2.0)


def plan(name: str, wanted_z: float, hardware, seam_y: float, bolt: Bolt,
         others: list[float] = (), surface=None, wall: float = 0.0,
         clearance: float = 0.3) -> ClampPlan:
    """Settle a clamp's height on the tube.

    The tube is 115 mm long and the clamp needs 22 of it plus an end margin at
    each end, so where it may go is a short run and the slider's track says so.
    A second clamp keeps CLAMP_MIN_GAP away from the first: two clamps close
    together hold the cover's tilt no better than one, and holding the tilt is
    the whole reason for the second.
    """
    lo, hi = hardware.clamp_band
    notes: list[str] = []
    if surface is not None:
        zs = np.arange(lo, hi + 0.5, 1.0)
        room = room_at(surface, wall, hardware, seam_y, zs).min(axis=1)
        good = zs[room >= bolt_reach(hardware, bolt) + clearance]
        if len(good) == 0:
            notes.append(
                f"No room for the {name} clamp: an M{bolt.diameter:.0f} lug wants "
                f"{bolt_reach(hardware, bolt) - hardware.tube.radius:.1f} mm past the tube "
                f"and the seam leaves {room.max() - hardware.tube.radius:.1f}"
            )
        else:
            lo, hi = float(good[0]), float(good[-1])
    z = float(np.clip(wanted_z, lo, hi))
    placed = not any("No room" in n for n in notes)
    for other in others:
        if abs(z - other) < cfg.CLAMP_MIN_GAP:
            up, down = other + cfg.CLAMP_MIN_GAP, other - cfg.CLAMP_MIN_GAP
            candidates = [c for c in (up, down) if lo <= c <= hi]
            if candidates:
                z = min(candidates, key=lambda c: abs(c - wanted_z))
            else:
                placed = False
                notes.append(
                    f"Only one clamp: the tube leaves {hi - lo:.0f} mm a clamp fits in "
                    f"and two need {cfg.CLAMP_MIN_GAP:.0f} between them"
                )
    if abs(z - wanted_z) > 0.5:
        notes.append(f"{name.capitalize()} clamp moved to {z:.0f} mm, where it fits")
    return ClampPlan(
        name=name, z=z, bolt=bolt,
        bore=hardware.tube.radius + cfg.BORE_CLEARANCE,
        ring=cfg.CLAMP_RING, height=cfg.CLAMP_HEIGHT,
        frame=hardware.tube.frame(z), seam_y=seam_y, placed=placed,
        lug_x=hardware.tube.radius + cfg.BORE_CLEARANCE + bolt.anchor_hole / 2.0 + cfg.LUG_STRUT,
        lo=lo, hi=hi, notes=notes,
    )


def _matrix(frame: np.ndarray) -> list[list[float]]:
    return frame.tolist()


def _ring_and_web(plan: ClampPlan) -> Manifold:
    """Ring, and the web running out of it, as one revolved solid.

    The profile is read in (radius, height) about the tube: full clamp height
    out to the ring's face, then down to the web's thickness over WEB_FLARE,
    then straight out past anything the cover can be.  Revolving it makes the
    root of the web a slope rather than a step, which is the fillet this part
    used not to have.
    """
    r0, r1 = plan.bore, plan.bore + plan.ring
    h, t, f = plan.height / 2.0, cfg.WEB_THICKNESS / 2.0, cfg.WEB_FLARE
    far = 400.0
    outline = [
        (r0, -h), (r1, -h), (r1 + f, -t), (far, -t),
        (far, t), (r1 + f, t), (r1, h), (r0, h),
    ]
    return CrossSection([outline]).revolve(circular_segments=128).transform(_matrix(plan.frame))


def _boss(surface, wall: float, plan: ClampPlan, steps: int = 3) -> Manifold:
    """A local thickening of the wall where the web lands on it.

    Stacked rather than swept: the wall is a loft over the cover's own grid and
    there is no fillet to apply to it, so the taper is three bands, each a
    little deeper and a little shorter than the last.  The steps are under two
    millimetres, which is below what the eye finds on the inside of a cover and
    well below what the section cares about.
    """
    parts = []
    for k in range(steps):
        share = (k + 1) / steps
        depth = wall + cfg.WEB_FLARE * share
        half = cfg.WEB_THICKNESS / 2.0 + cfg.WEB_FLARE * (1.0 - share)
        band = S.band(surface, wall - cfg.OVERLAP, depth)
        parts.append(band ^ S.slab([0.0, 0.0, plan.z], "z", half))
    return S.add(parts)


def _lugs(plan: ClampPlan) -> Manifold:
    """The two blocks the bolts run through, one each side of the tube."""
    b = plan.bolt
    y0 = plan.seam_y - plan.frame[1, 3]
    length = b.front_length + b.back_length + cfg.SPLIT_GAP
    centre_y = y0 + (b.front_length - b.back_length) / 2.0
    parts = []
    for sign in (+1.0, -1.0):
        block = Manifold.cube([b.lug_width, length, plan.height], center=True)
        parts.append(block.translate([sign * plan.lug_x, centre_y, 0.0]))
    return S.add(parts).transform(_matrix(plan.frame))


def _bolt_cuts(plan: ClampPlan) -> tuple[list[Manifold], list[Manifold]]:
    """What the bolts take out of the front part and out of the back one."""
    b = plan.bolt
    y0 = plan.seam_y - plan.frame[1, 3]
    front, back = [], []
    for sign in (+1.0, -1.0):
        x = sign * plan.lug_x
        # Front: the insert's hole, or the nut's pocket, opening on the cut.
        if b.kind == "heat_set":
            hole = Manifold.cylinder(b.anchor_depth, b.anchor_hole / 2.0, b.anchor_hole / 2.0, 48)
            hole = hole.rotate([-90.0, 0.0, 0.0]).translate([x, y0 + b.anchor_depth, 0.0])
            front.append(hole)
        else:
            through = Manifold.cylinder(b.front_length + 2.0, (b.diameter + 0.6) / 2.0,
                                        (b.diameter + 0.6) / 2.0, 32)
            front.append(through.rotate([-90.0, 0.0, 0.0])
                         .translate([x, y0 + b.front_length + 2.0, 0.0]))
            flats = cfg.HEX_NUT[b._size][0] + cfg.NUT_POCKET_CLEARANCE
            r = flats / math.sqrt(3.0)
            pocket = Manifold.cylinder(cfg.HEX_NUT[b._size][1] + cfg.NUT_POCKET_CLEARANCE, r, r, 6)
            pocket = pocket.rotate([-90.0, 0.0, 0.0])
            # Open to the top, so the nut drops in and cannot turn.
            slot = Manifold.cube([flats, cfg.HEX_NUT[b._size][1] + cfg.NUT_POCKET_CLEARANCE,
                                  plan.height], center=False)
            depth = y0 + b.anchor_depth + cfg.LUG_STRUT
            front.append(pocket.translate([x, depth, 0.0]))
            front.append(slot.translate([x - flats / 2.0, depth, 0.0]))
        # Back: a clearance hole all the way, and a seat for the head.
        clear = Manifold.cylinder(b.back_length + 4.0, (b.diameter + 0.6) / 2.0,
                                  (b.diameter + 0.6) / 2.0, 32).rotate([90.0, 0.0, 0.0])
        back.append(clear.translate([x, y0 + 2.0, 0.0]))
        head_d, head_h = b.head
        seat = Manifold.cylinder(head_h + 0.4 + 3.0, (head_d + 0.4) / 2.0,
                                 (head_d + 0.4) / 2.0, 40).rotate([90.0, 0.0, 0.0])
        back.append(seat.translate([x, y0 - b.back_length + head_h + 0.4, 0.0]))
    m = _matrix(plan.frame)
    return [c.transform(m) for c in front], [c.transform(m) for c in back]


def bodies(surface, wall: float, plan: ClampPlan, core: Manifold, seam_plane: float,
           clearance: float) -> tuple[Manifold, Manifold, Manifold]:
    """Front part (to be fused to the front half), back part, and the boss.

    The web is cut to the front of the seam and to the inside of the cover, so
    it reaches the wall everywhere it runs and stops there.  The back part
    keeps only the ring and its lugs -- a web on the back half would have to be
    a separate strap the size of the section, and the back half is held by the
    magnets and the step.
    """
    gap = cfg.SPLIT_GAP / 2.0
    stock = _ring_and_web(plan)
    lugs = _lugs(plan)
    bore = Manifold.cylinder(plan.height + 40.0, plan.bore, plan.bore, 96)
    bore = bore.translate([0.0, 0.0, -(plan.height + 40.0) / 2.0]).transform(_matrix(plan.frame))

    front_half = S.slab([0.0, plan.seam_y + 450.0 + gap, 0.0], "y", 450.0)
    back_half = S.slab([0.0, plan.seam_y - 450.0 - gap, 0.0], "y", 450.0)

    # Everything is trimmed to the inside of the cover.  The lugs reach
    # further from the tube than anything else on the clamp, and on the narrow
    # side of the anatomic cover's ankle they reach past the wall; `plan` keeps
    # the clamp off those heights, and this is the belt to that braces.
    web = (stock ^ core) ^ front_half
    front = S.add([web, (lugs ^ core) ^ front_half])
    ring_back = stock ^ Manifold.cylinder(
        plan.height + 2.0, plan.bore + plan.ring, plan.bore + plan.ring, 128
    ).translate([0.0, 0.0, -(plan.height + 2.0) / 2.0]).transform(_matrix(plan.frame))
    back = S.add([ring_back ^ back_half, (lugs ^ core) ^ back_half])

    front_cuts, back_cuts = _bolt_cuts(plan)
    front = S.sub(front, [bore, *front_cuts])
    back = S.sub(back, [bore, *back_cuts])
    return front, back, _boss(surface, wall, plan)
