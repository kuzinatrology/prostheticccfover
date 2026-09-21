"""What holds the cover on: magnets between the halves, clamps on the hardware.

Magnets. The wall is thinner than a magnet, so the front half carries a shelf
along the inside of each seam that reaches under the back half, and the back
half sits on it. Each magnet has a socket in the shelf and one in the back half
directly opposite, on the same surface normal. Under the back half's socket the
wall is thickened inward so the magnet never shows through; the shelf there
sits deeper by that thickening plus the fitting gap, so the thickening slides
over it.

Clamps. Two rings about the hardware, each cut by a frontal plane. The front
part is fused to the front half by ribs and printed with it; the back part is
its own body. Two bolts, left and right of the tube, pull them together: the
model carries their holes and the seats for their heads, not the bolts.

Every size here that is not a slider comes from the shell at that height and
from MIN_STRUT. Where there is not room, a slider stops; nothing is refused.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from manifold3d import CrossSection, Manifold
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from ..printer_profile import PrinterProfile
from . import config as cfg
from .layout import Layout
from .scan_surface import ScanSurface

CLAMP_SPLIT_GAP = 1.0
"""Gap between a clamp's two parts, mm, so the bolts have something to pull."""

RIB_ANGLES = (35.0, 90.0, 145.0)
"""Directions a clamp's ribs may take, degrees from +x in the clamp's plane.
All of them in front, where the front half is."""

MIN_RIBS = 2


# --- magnets ----------------------------------------------------------------------


@dataclass(frozen=True)
class MagnetSpec:
    diameter: float
    height: float
    count: int
    wall: float
    clearance: float
    min_strut: float
    curvature: float

    @property
    def socket_radius(self) -> float:
        return (self.diameter + self.clearance) / 2.0

    @property
    def socket_depth(self) -> float:
        return self.height + self.clearance

    @property
    def sagitta(self) -> float:
        """How far a flat socket floor dips under the curved face behind it."""
        return self.socket_radius**2 / (2.0 * max(self.curvature - 10.0, 5.0))

    @property
    def width(self) -> float:
        """The shelf: a socket and a strut either side of it.

        The brief gives magnet_diameter + 2 MIN_STRUT. The socket is wider than
        the magnet by the fitting gap, so that would leave the strut beside it
        short by half the gap; the gap is added.
        """
        return self.diameter + self.clearance + 2.0 * self.min_strut

    @property
    def pad(self) -> float:
        """Back half's thickness under a socket, measured from its outer face."""
        return max(self.wall, self.socket_depth + self.min_strut + self.sagitta)

    @property
    def shelf_top(self) -> float:
        return self.pad + self.clearance

    @property
    def shelf_thickness(self) -> float:
        return self.socket_depth + self.min_strut + self.sagitta

    @property
    def shelf_bottom(self) -> float:
        return self.shelf_top + self.shelf_thickness

    @property
    def flare(self) -> float:
        """Sideways room between the back half's thickening and the strip the
        shelf is fused to the front half by.

        Both are built along the surface normals, and where the leg is hollow
        the normals lean together: a part a thickening deep sits wider than its
        outline on the surface. Without this the two meet under the seam."""
        return 1.5

    @property
    def inner_edge(self) -> float:
        """Distance from the seam line to the near edge of the thickening and
        to the fused strip, mm."""
        return self.clearance / 2.0 + self.flare

    @property
    def solid_floor(self) -> float:
        """Narrowest pattern-free band either side of a seam that still covers
        the shelf."""
        return self.width + self.clearance + self.flare


@dataclass
class Magnet:
    side: int
    uv: tuple[float, float]
    point: np.ndarray
    normal: np.ndarray


def magnet_sites(
    layout: Layout,
    spec: MagnetSpec,
    avoid: list[tuple[float, float]] = (),
    pylon: Pylon | None = None,
) -> dict[int, list[Magnet]]:
    """Magnets down each seam, evenly spaced, clear of both ends.

    A seam runs from the bottom rim up to where it meets the notch. Its usable
    run stops where the shelf under the back half would come within half a
    shelf of the notch. The shelf breaks where a clamp passes (`avoid`) and
    narrows into the break over SHELF_RAMP; a magnet that would land in a
    break, or in the narrowing, moves to the nearest end of it.
    """
    surface = layout.surface
    centre_e = -(spec.inner_edge + spec.width / 2.0)
    z_rows = surface.z_of_v(layout.v)
    out: dict[int, list[Magnet]] = {}
    for sign, side in layout.sides.items():
        sites: list[tuple[float, float]] = []
        for j, z in enumerate(z_rows):
            if z < surface.z0 or z > side.meet:
                continue
            u = _crossing(layout, j, sign, centre_e)
            if u is None:
                continue
            k = int(round(u * len(layout.u))) % len(layout.u)
            if layout.notch[j, k] <= spec.width + 1.0:
                break
            if pylon is not None and not _clear_of_hardware(layout, spec, pylon, u, float(layout.v[j])):
                continue
            sites.append((u, float(layout.v[j])))
        if len(sites) < 2:
            out[sign] = []
            continue
        usable = [float(surface.z_of_v(s[1])) for s in sites]
        z_lo = surface.z_of_v(sites[0][1]) + cfg.MAGNET_END_MARGIN
        z_hi = surface.z_of_v(sites[-1][1]) - cfg.MAGNET_END_MARGIN
        if z_hi < z_lo:
            z_lo = z_hi = (z_lo + z_hi) / 2.0
        heights = [0.5 * (z_lo + z_hi)] if spec.count == 1 else list(np.linspace(z_lo, z_hi, spec.count))
        # A magnet needs the shelf at its full width under it, and beside a
        # gap the shelf is narrowing over SHELF_RAMP: stand that far off as
        # well, plus the socket's own half width.
        reach = spec.width / 2.0 + 1.0 + SHELF_RAMP
        free = []
        for z in heights:
            for lo, hi in avoid:
                if lo - reach < z < hi + reach:
                    below, above = lo - reach, hi + reach
                    z = below if (z - below <= above - z and below >= z_lo - cfg.MAGNET_END_MARGIN / 2.0) else above
                    if z > z_hi + cfg.MAGNET_END_MARGIN / 2.0:
                        z = below
            # Only where the seam run was clear of the hardware as well.
            beside = min(usable, key=lambda w: abs(w - z))
            if abs(beside - z) > 2.0 * layout.res.dz:
                continue
            if all(abs(z - w) >= spec.width + 1.0 for w in free) and all(
                not (lo - reach < z < hi + reach) for lo, hi in avoid
            ):
                free.append(z)
        heights = sorted(free)
        v_sites = np.array([s[1] for s in sites])
        u_sites = np.array([s[0] for s in sites])
        magnets = []
        for z in heights:
            v = float(surface.v_of_z(z))
            u = float(np.interp(v, v_sites, _unwrap(u_sites)))
            p, n = surface.frame(np.array([u]), np.array([v]))
            magnets.append(Magnet(side=sign, uv=(u, v), point=p[0], normal=n[0]))
        out[sign] = magnets
    return out


def _clear_of_hardware(layout: Layout, spec: MagnetSpec, pylon: Pylon, u: float, v: float) -> bool:
    """Whether a magnet's pad, shelf and sockets here stay a fitting gap off the
    tube and the module."""
    p, n = layout.surface.frame(np.array([u]), np.array([v]))
    p, n = p[0], n[0]
    side = np.cross(n, [0.0, 0.0, 1.0])
    side /= max(np.linalg.norm(side), 1e-9)
    up = np.cross(side, n)
    r = spec.width / 2.0 + 1.0
    rim = [p + (side * math.cos(a) + up * math.sin(a)) * r for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
    pts = np.array([q - n * d for q in rim + [p] for d in (spec.wall * 0.5, spec.shelf_top, spec.shelf_bottom)])
    # The same room a shelf needs to run at all (see `shelves`), and a little
    # more: a magnet where the shelf stops would have nothing under it.
    return bool(np.min(pylon.clearance_to(pts)) >= shelf_room(spec) + 0.5)


def shelf_room(spec: "MagnetSpec") -> float:
    """How far off the tube and the module a shelf keeps, mm."""
    return spec.clearance + spec.min_strut + 1.0


def _unwrap(u: np.ndarray) -> np.ndarray:
    return np.unwrap(u * 2.0 * math.pi) / (2.0 * math.pi)


def _crossing(layout: Layout, row: int, sign: int, level: float) -> float | None:
    """u where the seam field equals `level` on one side of one row."""
    e = layout.seam[row]
    on_side = layout.side[row] == sign
    nu = len(e)
    best = None
    for i in range(nu):
        j = (i + 1) % nu
        if not (on_side[i] and on_side[j]):
            continue
        a, b = e[i] - level, e[j] - level
        if a == 0 or (a < 0) != (b < 0):
            t = a / (a - b) if a != b else 0.0
            u = (layout.u[i] + t / nu)
            # The seam on this side, not the far edge of the back.
            if best is None or abs(e[i]) < abs(layout.seam[row][int(round(best * nu)) % nu]):
                best = u
    return best


SHELF_RAMP = 14.0
"""Height, mm, a shelf narrows over as it runs into a gap."""

SHELF_STUB = 0.25
"""What is left of a shelf's width where it meets a gap, as a fraction.

Not zero: a shelf that ran out to a point would end in a wedge thinner than a
strut, which is what stopping it short was avoiding in the first place."""


def band_field(layout: Layout, sign: int, lo, hi, top: float, margin: float) -> np.ndarray:
    """Positive on one side where lo < seam field < hi, below `top`, clear of
    the notch by `margin`.

    `lo` and `hi` are millimetres across the seam, either a number or a column
    of one per row of the grid, which is how a band is narrowed with height."""
    z = layout.surface.z_of_v(layout.v)[:, None]
    f = np.minimum(layout.seam - lo, hi - layout.seam)
    f = np.minimum(f, top - z)
    f = np.minimum(f, layout.notch - margin)
    return np.where(layout.side == sign, f, -1.0)


def shelf_gaps(plans, clearance: float) -> list[tuple[float, float]]:
    """Heights a shelf leaves free so a clamp and its ribs pass it."""
    gaps = []
    for plan in plans:
        if plan.ring <= 0.0:
            continue
        # The clamp is tilted with the pylon, so its plane spans a little more
        # height at the seams than its own thickness.
        reach = plan.shape.lug_x + plan.ring
        tilt = math.sqrt(max(1.0 - plan.frame[2, 2] ** 2, 0.0))
        half = plan.shape.height / 2.0 + reach * tilt + clearance + 1.0
        gaps.append((plan.z - half, plan.z + half))
    return gaps


def shelves(layout: Layout, spec: MagnetSpec, chord: float, gaps=(), pylon: Pylon | None = None) -> list[Manifold]:
    """The front half's shelves, one down each seam, broken where clamps pass
    and where the tube or the module comes within a fitting gap and a strut.

    Stopping the shelf short, rather than cutting the hardware out of it, is
    what keeps a shelf from ending in a wedge thinner than a strut."""
    from .. import mesh_build as mb

    room = None
    if pylon is not None:
        uu, vv = np.meshgrid(layout.u, layout.v)
        p, n = layout.surface.frame(uu, np.clip(vv, 0.0, 1.0))
        room = np.full(uu.shape, np.inf)
        for depth in (spec.wall * 0.5, spec.shelf_top, spec.shelf_bottom):
            q = (p - n * depth).reshape(-1, 3)
            room = np.minimum(room, pylon.clearance_to(q).reshape(uu.shape))
        room = room - shelf_room(spec)

    clear = layout.clearance / 2.0
    out = []
    for sign, side in layout.sides.items():
        centre = 0.0 if sign == 1 else 0.5
        top = side.meet
        edge = spec.inner_edge
        z = layout.surface.z_of_v(layout.v)[:, None]
        # A shelf that simply stops leaves an eight millimetre step in the
        # outline of the half, once per clamp. Instead it narrows into every
        # gap over SHELF_RAMP, down to SHELF_STUB of its width, and the step
        # left in the outline is that stub rather than the whole shelf.
        taper = np.ones_like(z)
        for lo, hi in gaps:
            outside = np.maximum(lo - z, z - hi)
            taper = np.minimum(taper, np.clip(outside / SHELF_RAMP, SHELF_STUB, 1.0))
        under = band_field(layout, sign, -(edge + spec.width * taper), edge + spec.width * taper, top, spec.width / 2.0)
        fused = band_field(layout, sign, edge, edge + spec.width * taper, top, spec.width / 2.0)
        if room is not None:
            under = np.minimum(under, room)
            fused = np.minimum(fused, room)
        for lo, hi in gaps:
            outside = np.maximum(lo - z, z - hi)
            under = np.minimum(under, outside)
            fused = np.minimum(fused, outside)
        parts = []
        for region, outer, inner in (
            (layout.region(under, centre), -spec.shelf_top, -spec.shelf_bottom),
            (layout.region(fused, centre), -spec.wall * 0.5, -(spec.shelf_top + 0.5)),
        ):
            for poly in region.geoms:
                body = mb.slab(layout.surface, poly, outer, inner, chord)
                if body is not None:
                    parts.append(mb.to_manifold(body))
        if parts:
            out.append(Manifold.batch_boolean(parts, _ADD))
    return out


def pads(layout: Layout, spec: MagnetSpec, sites: dict[int, list[Magnet]], chord: float) -> list[Manifold]:
    """The back half's thickening under each socket."""
    from .. import mesh_build as mb

    radius = spec.width / 2.0
    out = []
    for magnets in sites.values():
        for m in magnets:
            su, sv = layout.uv_mm(*m.uv)
            ring = [
                (m.uv[0] + radius / su * math.cos(a), m.uv[1] + radius / sv * math.sin(a))
                for a in np.linspace(0.0, 2.0 * math.pi, 40, endpoint=False)
            ]
            body = mb.slab(layout.surface, Polygon(ring), -spec.wall * 0.5, -spec.pad, min(chord, radius))
            if body is not None:
                out.append(mb.to_manifold(body))
    return out


def along_normal(point: np.ndarray, normal: np.ndarray, radius: float, depth_from: float, depth_to: float) -> Manifold:
    """A cylinder on the surface normal, between two depths below the surface."""
    length = depth_to - depth_from
    cyl = Manifold.cylinder(length, radius, radius, 48)
    inward = -normal / np.linalg.norm(normal)
    return Manifold.transform(cyl, _frame_to(point + normal * -depth_from, inward))


def sockets(spec: MagnetSpec, sites: dict[int, list[Magnet]]) -> tuple[list[Manifold], list[Manifold]]:
    """Sockets in the back half and in the shelf, each pair on one normal."""
    r = spec.socket_radius
    back, front = [], []
    for magnets in sites.values():
        for m in magnets:
            back.append(along_normal(m.point, m.normal, r, spec.pad - spec.socket_depth, spec.pad + 1.0))
            front.append(
                along_normal(m.point, m.normal, r, spec.shelf_top - 1.0, spec.shelf_top + spec.socket_depth)
            )
    return back, front


# --- clamps ------------------------------------------------------------------------


@dataclass(frozen=True)
class Pylon:
    """The tube and the module, as a straight line from ankle to knee."""

    origin: np.ndarray
    direction: np.ndarray
    knee: np.ndarray

    @classmethod
    def for_surface(cls, surface: ScanSurface, knee_axis_y: float) -> Pylon:
        c0 = surface.centre(surface.z0)
        ck = surface.centre(cfg.knee_axis_z)
        a = np.array([c0[0], c0[1], surface.z0])
        k = np.array([ck[0], knee_axis_y, cfg.knee_axis_z])
        d = (k - a) / np.linalg.norm(k - a)
        return cls(a, d, k)

    def at(self, z: float) -> np.ndarray:
        return self.origin + self.direction * (z - self.origin[2]) / self.direction[2]

    @property
    def module_bottom_z(self) -> float:
        return float((self.knee - self.direction * cfg.MODULE_KNEE_TO_TUBE)[2])

    @property
    def tilt_deg(self) -> float:
        return math.degrees(math.acos(self.direction[2]))

    def clearance_to(self, pts: np.ndarray) -> np.ndarray:
        """How far each point is outside the tube and the module, mm.

        Negative inside. The module is a box on the knee end of the line, the
        tube a cylinder below it; both are measured across the line."""
        f = self.frame(self.origin[2])
        ex, ey, ez = f[:, 0], f[:, 1], f[:, 2]
        d = np.asarray(pts, dtype=float) - self.origin
        along = d @ ez
        x, y = d @ ex, d @ ey
        bottom = float((self.knee - self.origin) @ ez) - cfg.MODULE_KNEE_TO_TUBE
        tube = np.hypot(x, y) - cfg.PYLON_DIAMETER / 2.0
        qx = np.abs(x) - cfg.UPPER_HOLE_WIDTH / 2.0
        qy = np.abs(y) - cfg.UPPER_HOLE_DEPTH / 2.0
        box = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0)) + np.minimum(np.maximum(qx, qy), 0.0)
        return np.where(along <= bottom, tube, box)

    def frame(self, z: float) -> np.ndarray:
        """3x4: local x across, y forward, z along the pylon, origin on it."""
        ez = self.direction
        ey = np.array([0.0, 1.0, 0.0]) - ez[1] * ez
        ey /= np.linalg.norm(ey)
        ex = np.cross(ey, ez)
        o = self.at(z)
        return np.column_stack([ex, ey, ez, o])


@dataclass(frozen=True)
class ClampShape:
    kind: str
    """"round" or "rect"."""
    hole_x: float
    """Half-width of the hole across, mm."""
    hole_y: float
    """Half-depth of the hole front to back, mm."""
    bolt: float
    min_strut: float
    clearance: float

    @property
    def head(self) -> float:
        return cfg.BOLT_HEAD_RATIO * self.bolt

    @property
    def head_height(self) -> float:
        return cfg.BOLT_HEAD_HEIGHT_RATIO * self.bolt

    @property
    def height(self) -> float:
        return max(10.0, self.head + self.clearance + 2.0 * self.min_strut)

    @property
    def bolt_x(self) -> float:
        # Clear of the part in the hole, with the head's seat as well.
        return self.hole_x + max(
            self.bolt / 2.0 + self.min_strut, (self.head + self.clearance) / 2.0 + self.clearance
        )

    @property
    def lug_x(self) -> float:
        return self.bolt_x + (self.head + self.clearance) / 2.0 + self.min_strut

    @property
    def lug_y(self) -> float:
        return max(
            (self.head + self.clearance) / 2.0 + self.min_strut,
            CLAMP_SPLIT_GAP / 2.0 + self.head_height + self.clearance + 2.0 * self.min_strut,
        )

    def hole(self) -> Polygon:
        if self.kind == "round":
            return Point(0, 0).buffer(self.hole_x, 64)
        r = self.corner
        return box(-self.hole_x + r, -self.hole_y + r, self.hole_x - r, self.hole_y - r).buffer(r, 16)

    @property
    def corner(self) -> float:
        """The rectangular hole's corner radius: MIN_STRUT, as the brief asks."""
        return self.min_strut

    def outline(self, ring: float) -> Polygon:
        """Ring, lugs, minus the hole, in the clamp's own plane."""
        if self.kind == "round":
            body = Point(0, 0).buffer(self.hole_x + ring, 64)
        else:
            r = self.corner + ring
            body = box(
                -self.hole_x - ring + r, -self.hole_y - ring + r, self.hole_x + ring - r, self.hole_y + ring - r
            ).buffer(r, 16)
        lugs = box(-self.lug_x, -self.lug_y, self.lug_x, self.lug_y)
        return unary_union([body, lugs]).difference(self.hole())


@dataclass
class ClampPlan:
    name: str
    shape: ClampShape
    z: float
    ring: float
    ribs: list[tuple[float, float, float]]
    """(angle deg, start radius, end radius) of each rib in the clamp plane."""
    rib_width: float
    lo: float
    hi: float
    frame: np.ndarray
    notes: list[str] = field(default_factory=list)


def _to_world(frame: np.ndarray, local: np.ndarray) -> np.ndarray:
    return local @ frame[:, :3].T + frame[:, 3]


def _depth(surface: ScanSurface, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Radial depth below the outer surface, and the seam field there."""
    c = surface.centre(pts[:, 2])
    dx, dy = pts[:, 0] - c[:, 0], pts[:, 1] - c[:, 1]
    theta = np.arctan2(dy, dx)
    rho = np.hypot(dx, dy)
    R = surface.radial(theta, pts[:, 2])
    return R - rho, R * np.sin(theta)


def _envelope(layout: Layout, spec: MagnetSpec, pts: np.ndarray, sites: dict[int, list[Magnet]]) -> np.ndarray:
    """How far each point is inside the shell's inner face, mm.

    The shelves are not counted: where a clamp sits, the shelf stops short of
    it (see `shelf_gaps`). The back half's thickenings are, because those sit
    where the magnets are and cannot move.
    """
    depth, _ = _depth(layout.surface, pts)
    need = np.full(len(pts), spec.wall)
    for magnets in sites.values():
        for m in magnets:
            near = np.linalg.norm(pts - m.point, axis=1) <= spec.width / 2.0 + 1.0
            need = np.where(near, spec.shelf_bottom, need)
    return depth - need


def plan_clamp(
    name: str,
    shape: ClampShape,
    wanted_z: float,
    layout: Layout,
    spec: MagnetSpec,
    pylon: Pylon,
    profile: PrinterProfile,
    sites: dict[int, list[Magnet]],
) -> ClampPlan:
    """Settle a clamp's height, ring and ribs, stopping where there is no room."""
    surface = layout.surface
    h = shape.height
    mb_z = pylon.module_bottom_z
    if name == "lower":
        z_min, z_max = surface.z0 + h, mb_z - h / 2.0 - profile.CLEARANCE
    else:
        z_min, z_max = mb_z + h / 2.0 + profile.CLEARANCE, cfg.knee_axis_z
    good = []
    for z in np.arange(math.ceil(z_min), math.floor(z_max) + 1e-9, 4.0):
        found = _fit(shape, float(z), layout, spec, pylon, profile, sites)
        if found is not None:
            good.append((float(z), found))
    # Ends of the run to the millimetre: a slider stops where the room does.
    if good:
        for end, step in ((good[0][0], -1.0), (good[-1][0], 1.0)):
            z = end + step
            while z_min <= z <= z_max:
                found = _fit(shape, float(z), layout, spec, pylon, profile, sites)
                if found is None:
                    break
                good.append((float(z), found))
                z += step
        good.sort(key=lambda g: g[0])
    if not good:
        plan = ClampPlan(name, shape, float(np.clip(wanted_z, z_min, z_max)), 0.0, [], 0.0, z_min, z_max, pylon.frame(wanted_z))
        plan.notes.append(f"No room for the {name} clamp at this size")
        return plan
    lo, hi = good[0][0], good[-1][0]
    z, (ring, ribs, width) = min(good, key=lambda g: abs(g[0] - wanted_z))
    return ClampPlan(name, shape, z, ring, ribs, width, lo, hi, pylon.frame(z))


def _fit(shape, z, layout, spec, pylon, profile, sites):
    """Ring thickness and ribs at one height, or None when it does not fit."""
    frame = pylon.frame(z)
    h = shape.height
    # How much room the hardware has, around the hole, in this plane.
    probe = np.linspace(0.0, 2.0 * math.pi, 48, endpoint=False)
    directions = np.stack([np.cos(probe), np.sin(probe)], axis=1)
    starts = np.array([_hole_reach(shape, a) for a in probe])
    gap = max(float(np.min(_free_runs(layout, spec, frame, starts, directions, sites))), 0.0)
    ring = float(np.clip(0.3 * gap, 3.0 * profile.MIN_STRUT, 6.0))
    outline = shape.outline(ring)
    ring_pts = []
    for geom in [outline] if outline.geom_type == "Polygon" else outline.geoms:
        coords = np.asarray(geom.exterior.coords)
        ring_pts.append(coords)
    pts2 = np.vstack(ring_pts)
    local = np.vstack(
        [np.column_stack([pts2, np.full(len(pts2), s)]) for s in (-h / 2.0, h / 2.0)]
    )
    world = _to_world(frame, local)
    if np.min(_envelope(layout, spec, world, sites)) < profile.CLEARANCE:
        return None
    # The sector is kept clear by the hardware as well as by the shell. The
    # clamp round the module is the exception: the module stands in the sector
    # itself, fixed to the shin, so no thigh ever reaches there, and a ring
    # that hugs it cannot be anywhere else.
    if shape.kind == "round" and np.min(layout.knee.sector_distance(world)) <= layout.knee.fillet:
        return None
    ribs = []
    width = max(2.5 * profile.MIN_STRUT, min(8.0, 0.5 * h))
    for angle in RIB_ANGLES:
        rib = _rib(shape, ring, angle, width, h, layout, spec, frame, sites)
        if rib is not None:
            ribs.append(rib)
    if len(ribs) < MIN_RIBS:
        return None
    return ring, ribs, width


def _hole_reach(shape: ClampShape, angle: float) -> float:
    c, s = abs(math.cos(angle)), abs(math.sin(angle))
    if shape.kind == "round":
        return shape.hole_x
    return min(shape.hole_x / max(c, 1e-9), shape.hole_y / max(s, 1e-9))


def _free_runs(layout, spec, frame, starts, directions, sites, step=0.5, limit=150.0):
    """Distance from the pylon along each direction before the room ends."""
    t = np.arange(0.0, limit, step)
    k = len(directions)
    local = np.zeros((k, len(t), 3))
    for i, (s0, d) in enumerate(zip(starts, directions)):
        local[i, :, 0] = d[0] * (s0 + t)
        local[i, :, 1] = d[1] * (s0 + t)
    env = _envelope(layout, spec, _to_world(frame, local.reshape(-1, 3)), sites).reshape(k, len(t))
    out = np.full(k, limit)
    for i in range(k):
        bad = np.nonzero(env[i] < 0.0)[0]
        if len(bad):
            out[i] = t[bad[0]]
    return out


def _rib(shape, ring, angle, width, h, layout, spec, frame, sites):
    """A rib from the ring out into the front wall, or None where it cannot go.

    Its end is flat and the wall is not square to it, so each of the end's four
    corners is followed: the rib stops once every corner is past the inner face
    of the wall, and is refused if any corner would then be through the outer
    one.
    """
    a = math.radians(angle)
    d = np.array([math.cos(a), math.sin(a)])
    n = np.array([-d[1], d[0]])
    start = _hole_reach(shape, a) + ring / 2.0
    t = np.arange(start, 160.0, 0.25)
    lines = []
    for off in (-width / 2.0, width / 2.0):
        for lift in (-h / 2.0, h / 2.0):
            lines.append(np.column_stack([d[0] * t + n[0] * off, d[1] * t + n[1] * off, np.full(len(t), lift)]))
    world = _to_world(frame, np.vstack(lines))
    depth, y_rel = _depth(layout.surface, world)
    depth = depth.reshape(4, len(t))
    y_rel = y_rel.reshape(4, len(t))
    world = world.reshape(4, len(t), 3)
    ends_in, ends_out = [], []
    for c in range(4):
        inside = np.nonzero(depth[c] <= spec.wall)[0]
        through = np.nonzero(depth[c] <= 0.3)[0]
        if not len(inside) or not len(through):
            return None
        k = inside[0]
        ends_in.append(float(t[k]))
        ends_out.append(float(t[through[0]]))
        seam = y_rel[c, k] + layout.seam_shift + layout.seam_offset
        # In the front half, clear of the shelf and its fused strip.
        if seam <= spec.inner_edge + spec.width + 2.0 + width / 2.0:
            return None
        u, v = layout.surface.uv_of_point(world[c, k])
        if v <= 0.02 or v >= 0.98:
            return None
        nu = len(layout.u)
        j = int(np.clip(np.searchsorted(layout.v, v), 0, len(layout.v) - 1))
        if layout.notch[j, int(u * nu) % nu] <= width:
            return None
    end = max(ends_in) + 0.3
    if end >= min(ends_out):
        return None
    return (angle, start, end)


def clamp_bodies(plan: ClampPlan, profile: PrinterProfile) -> tuple[Manifold | None, Manifold | None, list[np.ndarray]]:
    """Front part with its ribs, back part, and where the ribs meet the wall."""
    if plan.ring <= 0.0:
        return None, None, []
    shape = plan.shape
    h = shape.height
    section = _cross_section(shape.outline(plan.ring))
    ring = section.extrude(h).translate([0.0, 0.0, -h / 2.0])
    big = 400.0
    gap = CLAMP_SPLIT_GAP / 2.0
    front_keep = Manifold.cube([big, big, big]).translate([-big / 2.0, gap, -big / 2.0])
    back_keep = Manifold.cube([big, big, big]).translate([-big / 2.0, -big - gap, -big / 2.0])
    front = ring ^ front_keep
    back = ring ^ back_keep

    feet = []
    ribs = []
    for angle, start, end in plan.ribs:
        rib = Manifold.cube([end - start, plan.rib_width, h]).translate([start, -plan.rib_width / 2.0, -h / 2.0])
        rib = rib.rotate([0.0, 0.0, angle])
        ribs.append(rib)
        a = math.radians(angle)
        feet.append(_to_world(plan.frame, np.array([[math.cos(a) * end, math.sin(a) * end, 0.0]]))[0])
    front = Manifold.batch_boolean([front, *ribs], _ADD)

    # Bolts run front to back beside the hole; heads seat in the back part.
    cuts_front, cuts_back = [], []
    for sx in (-1.0, 1.0):
        bolt = Manifold.cylinder(big, shape.bolt / 2.0, shape.bolt / 2.0, 32).rotate([-90.0, 0.0, 0.0])
        bolt = bolt.translate([sx * shape.bolt_x, -big / 2.0, 0.0])
        seat_depth = shape.head_height + profile.CLEARANCE
        seat = Manifold.cylinder(seat_depth + 5.0, (shape.head + profile.CLEARANCE) / 2.0, -1.0, 40)
        seat = seat.rotate([-90.0, 0.0, 0.0]).translate([sx * shape.bolt_x, -shape.lug_y - 5.0, 0.0])
        cuts_front.append(bolt)
        cuts_back.extend([bolt, seat])
    front = Manifold.batch_boolean([front, *cuts_front], _SUB)
    back = Manifold.batch_boolean([back, *cuts_back], _SUB)
    m = _matrix(plan.frame)
    return front.transform(m), back.transform(m), feet


def head_volumes(plan: ClampPlan) -> Manifold | None:
    """Where the bolt heads sit once tightened, for the fit check."""
    if plan.ring <= 0.0:
        return None
    shape = plan.shape
    parts = []
    for sx in (-1.0, 1.0):
        head = Manifold.cylinder(shape.head_height, shape.head / 2.0, -1.0, 32).rotate([-90.0, 0.0, 0.0])
        parts.append(head.translate([sx * shape.bolt_x, -shape.lug_y, 0.0]))
    return Manifold.batch_boolean(parts, _ADD).transform(_matrix(plan.frame))


def hardware(pylon: Pylon, surface: ScanSurface, grow: float = 0.0) -> Manifold:
    """The tube and the module, grown by `grow`. Never printed."""
    z_mb = pylon.module_bottom_z
    tube_len = z_mb - surface.z0 + 20.0
    tube = Manifold.cylinder(tube_len + grow, cfg.PYLON_DIAMETER / 2.0 + grow, -1.0, 96)
    tube = tube.translate([0.0, 0.0, -tube_len]).transform(_matrix(pylon.frame(z_mb)))
    module_len = cfg.top_z - z_mb + 80.0
    w, d = cfg.UPPER_HOLE_WIDTH + 2.0 * grow, cfg.UPPER_HOLE_DEPTH + 2.0 * grow
    module = Manifold.cube([w, d, module_len]).translate([-w / 2.0, -d / 2.0, -grow])
    module = module.transform(_matrix(pylon.frame(z_mb)))
    return tube + module


# --- manifold helpers --------------------------------------------------------------

from manifold3d import OpType

_ADD = OpType.Add
_SUB = OpType.Subtract


def _cross_section(poly) -> CrossSection:
    """Manifold fills counter-clockwise outlines; shapely promises no order."""
    from shapely.geometry.polygon import orient

    rings = []
    for geom in [poly] if poly.geom_type == "Polygon" else poly.geoms:
        geom = orient(geom, 1.0)
        rings.append(np.asarray(geom.exterior.coords)[:-1][::1].tolist())
        for hole in geom.interiors:
            rings.append(np.asarray(hole.coords)[:-1].tolist())
    return CrossSection(rings)


def _matrix(frame: np.ndarray) -> list[list[float]]:
    return frame.tolist()


def _frame_to(origin: np.ndarray, z_axis: np.ndarray) -> list[list[float]]:
    ez = z_axis / np.linalg.norm(z_axis)
    helper = np.array([1.0, 0.0, 0.0]) if abs(ez[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    ex = np.cross(helper, ez)
    ex /= np.linalg.norm(ex)
    ey = np.cross(ez, ex)
    return np.column_stack([ex, ey, ez, origin]).tolist()


