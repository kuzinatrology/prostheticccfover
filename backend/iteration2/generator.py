"""The second modelled cover, from its parameters to four printable bodies.

    front               the front half, with the land, the tongue, the magnet
                        pockets, and the web and front part of every clamp
                        that has one
    back                the back half, with the land, the groove and its pockets
    lower_clamp_*       both halves of the free clamp, which grips the pylon
                        and is screwed to neither half of the cover
    upper_clamp_back    the strap that closes the webbed clamp round the pylon

The shape, the wall and the pattern are the modelled tab's, built by
`iteration1.generate` on this model's stored surface.  What is added is the
attachment, and the order matters: the seam and the clamps are planned first,
the pattern is laid with those places kept solid, and only then is anything
cut.  A hole under the land or under a web is a hole in the part that holds
the cover on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from .. import mesh_build as mb
from ..fasteners import Hardware
from ..fasteners import kit as fkit
from ..iteration1.generator import DRAFT, FINAL, Quality
from ..iteration1.generator import generate as it_generate
from ..iteration1.surface import IterSurface
from ..printer_profile import DEFAULT_PROFILE, PrinterProfile
from .params import MODEL, Iter2Params

BODY_NAMES = ("front", "back",
              "lower_clamp_front", "lower_clamp_back",
              "upper_clamp_front", "upper_clamp_back")
"""Every body the tab can produce, in the order they are listed and zipped.

A free clamp -- the lower one -- is two loose halves and both are its own
body; a clamp with a web has only a back part, because its front is printed
as part of the front half of the cover.  Which of these exist depends on the
settings, so the exporter skips what is not there."""

__all__ = ["DRAFT", "FINAL", "Iter2Cover", "generate", "audit", "BODY_NAMES"]


@dataclass
class Iter2Cover:
    bodies: dict[str, trimesh.Trimesh]
    params: Iter2Params
    profile: PrinterProfile
    volumes: dict[str, float] = field(default_factory=dict)
    masses: dict[str, float] = field(default_factory=dict)
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
    seam: object = field(repr=False, default=None)
    clamps: list = field(repr=False, default_factory=list)
    rings: list = field(repr=False, default_factory=list)
    """The holes as outlines in (u, v) -- the design itself, in coordinates
    that do not know how big the cover is."""

    sweep_solid: object = field(repr=False, default=None)
    """The notch and the trimmed top, as one solid."""

    loose_clamps: dict = field(repr=False, default_factory=dict)
    """Every clamp body at full size, the webbed one's front part included."""

    @property
    def mesh(self) -> trimesh.Trimesh:
        """The whole thing, for anything that wants one mesh."""
        return trimesh.util.concatenate(list(self.bodies.values()))


def _fastener_params(p: Iter2Params) -> fkit.FastenerParams:
    return fkit.FastenerParams(
        magnet_count=p.magnets,
        seam_curve=p.seam_curve,
        flexion=p.flexion,
        magnet_diameter=p.magnet_diameter,
        magnet_height=p.magnet_height,
        bolt_diameter=p.bolt_diameter,
        nut_kind=p.nut_kind,
        lower_clamp_z=p.lower_clamp_z,
        upper_clamp_z=p.upper_clamp_z,
        clamps=p.clamps,
    )


def generate(
    params: Iter2Params,
    *,
    quality: Quality = FINAL,
    profile: PrinterProfile = DEFAULT_PROFILE,
) -> Iter2Cover:
    p = params.clamped()
    surface = IterSurface.default(p.surface_smoothing, p.shape, MODEL)
    hardware = Hardware.for_tab(MODEL)
    fp = _fastener_params(p)

    rows = 160 if quality is DRAFT else 240
    plans = fkit.plan(surface, p.wall_thickness, hardware, fp, profile, rows)
    seam_plan, clamps, notes, sweep = plans
    keep_clear = fkit.solid_field(surface, seam_plan, clamps, sweep)
    edges = fkit.edge_field(surface, seam_plan, clamps, sweep)

    def leaf_room(u, v):
        """How far a leaf is from anything it must not cross, in millimetres.

        The cover's own rims, the seam the halves part on, the notch, and any
        clamp with a web -- the same four kinds of edge the transfemoral tab
        keeps its leaves off.
        """
        rim = surface.edge_distance(u, v) - p.rim_solid
        return np.minimum(rim, edges(u, v))

    leaves = None
    if p.back_leaves:
        from .. import anatomic_leaves as lv

        def back_of_seam(centres: np.ndarray) -> np.ndarray:
            """Which cells sit on the back half.

            All of them come out.  The transfemoral tab settled this: the
            leaves are the back half's pattern, and cells beside them only
            blur the drawing.  Here the back half is a separate body, so the
            split is exactly the seam the cover is cut on.
            """
            q = surface.point(centres[:, 0], centres[:, 1])
            return q[..., 1] < seam_plan.y_at(q[..., 2])

        def leaves(surface_, cells, strut):
            if cells is None:
                return [], [], None
            rings_, notes_ = lv.place(
                surface_,
                lv.LeafSpec(
                    count=int(round(p.leaf_count)),
                    length=p.leaf_size,
                    tilt=p.leaf_tilt,
                    strut=strut,
                    a_max=cells.a_max,
                    profile=profile,
                ),
                keep_at=leaf_room,
            )[:2]
            return rings_, notes_, back_of_seam

    base = it_generate(p, quality=quality, profile=profile, keep_clear=keep_clear,
                       extra_holes=leaves)

    kit = fkit.build(
        mb.to_manifold(base.mesh), surface, base.wall, hardware, fp, profile, rows, plans
    )

    density = p.material_spec.density
    bodies = {k: mb.from_manifold(v) for k, v in kit.bodies.items()}
    volumes = {k: float(m.volume) for k, m in bodies.items()}
    masses = {k: v / 1000.0 * density for k, v in volumes.items()}
    mass = sum(masses.values())
    # The plain mass is the cover's own, before the pattern: the fasteners are
    # solid either way, so they are added to both sides of the comparison and
    # the saving stays the saving the pattern made.
    extra = max(mass - base.mass_g, 0.0)
    plain = base.plain_mass_g + extra

    return Iter2Cover(
        bodies=bodies,
        params=p,
        profile=profile,
        volumes=volumes,
        masses=masses,
        mass_g=mass,
        plain_mass_g=plain,
        saving_pct=(1.0 - mass / plain) * 100.0 if plain > 0 else 0.0,
        holes=base.holes,
        wall=base.wall,
        max_wall=base.max_wall,
        max_relief=base.max_relief,
        notes=[*base.notes, *notes, *kit.notes],
        limits={**base.limits, **kit.limits},
        surface=surface,
        seam=kit.seam,
        clamps=kit.clamps,
        rings=base.rings,
        sweep_solid=kit.cut,
        loose_clamps=kit.clamp_parts,
    )


def audit(cover: Iter2Cover) -> list[str]:
    """What must be true of every body before a file is written."""
    faults = []
    for name, m in cover.bodies.items():
        if not m.is_watertight:
            faults.append(f"{name}: not closed")
        if m.body_count > 1:
            faults.append(f"{name}: {m.body_count} pieces")
        if m.volume <= 0:
            faults.append(f"{name}: no volume")
    if "front" not in cover.bodies or "back" not in cover.bodies:
        faults.append("a half is missing")
    return faults
