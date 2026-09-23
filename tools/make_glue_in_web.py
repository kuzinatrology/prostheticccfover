"""The cross-wall that is missing from a cover already printed, as a glue-in part.

    .venv/bin/python -m tools.make_glue_in_web

The front half was printed before the lower clamp was built into it, so the
wall that grips the pylon at 120 mm is not there.  It cannot simply be printed
on its own and glued edge-on: that is a strip of adhesive as wide as the wall
is thick, loaded in the one direction adhesive is worst at -- peeling from one
edge, the way tape lifts once a corner is started.

So it is printed with a band that lies flat on the inside of the cover.  Same
part, three times the bonded area, and the load arrives along the joint rather
than across it.

Nothing about the tab changes; this reads the same geometry the tab builds and
writes two STLs.
"""

from __future__ import annotations

import json
import pathlib

import numpy as np

from backend import mesh_build as mb
from backend.fasteners import seam as sm
from backend.fasteners import solids as S
from backend.iteration2.generator import DRAFT, FINAL, generate
from backend.iteration2.params import Iter2Params

OUT = pathlib.Path(__file__).resolve().parents[1] / "out"
LAST = OUT / "last_build.json"

GLUE_GAP = 0.2
"""Space left between the band and the wall, mm.

A part pressed dry against a wall squeezes the adhesive out of the joint and
what is left is a film too thin to hold.  This is the film's thickness."""

BAND_THICKNESS = 2.0
BAND_HEIGHT = 20.0
"""The band: how thick it stands off the wall and how far up and down it runs.
Twenty millimetres over the arc is 29 cm2 against the 10 an edge would give."""

SEAM_KEEP = 8.0
"""How far the band stops short of where the halves meet, mm.

The printed cover carries a thickening along that edge and the band must not
foul it.  The web and its bolt lugs sit far inside and are not affected."""

PRINTED_LAND_HALF = 7.5
PRINTED_LAND_DEPTH = 10.0
"""The thickening along the inside of the seam on the cover already printed.

Measured off the file: about 9 mm deep and a little over 6 mm either side of
the cut.  What the tab builds today is 2.55 mm, so this is the cover that
exists rather than the cover the code describes."""

BUMPS = 5
BUMP_RADIUS = 2.5
"""Little feet that hold the band off the wall by exactly GLUE_GAP, so the
film is the thickness it was meant to be all the way round."""


def main() -> None:
    raw = json.loads(LAST.read_text())["iter2"]["params"]
    params = Iter2Params.from_dict(raw)
    cover = generate(params, quality=FINAL)
    surface = cover.surface
    wall = cover.wall
    seam = cover.seam
    low = next(q for q in cover.clamps if q.name == "lower")
    web = cover.loose_clamps["lower_clamp_front"]
    z = low.z

    curve = (seam.z_curve, seam.y_curve)
    front = S.curved_half(*curve, +1, SEAM_KEEP)
    rows = 240

    band = S.band(surface, wall + GLUE_GAP, wall + GLUE_GAP + BAND_THICKNESS, rows=rows)
    band = (band ^ S.slab([0.0, 0.0, z], "z", BAND_HEIGHT / 2.0)) ^ front

    # The feet: the same band brought right up to the wall, kept only where a
    # foot goes.
    touch = S.band(surface, wall, wall + GLUE_GAP + 0.01, rows=rows)
    touch = (touch ^ S.slab([0.0, 0.0, z], "z", BAND_HEIGHT / 2.0)) ^ front
    feet = []
    theta = np.linspace(0.0, 2.0 * np.pi, 720, endpoint=False)
    zz = np.full_like(theta, z)
    c = S.centre_of(surface, zz)
    r = surface.radial(theta, zz)
    x, y = c[:, 0] + r * np.cos(theta), c[:, 1] + r * np.sin(theta)
    keep = y > np.interp(z, seam.z_curve, seam.y_curve) + SEAM_KEEP + 4.0
    px, py = x[keep], y[keep]
    for k in np.linspace(0, len(px) - 1, BUMPS + 2)[1:-1].astype(int):
        from manifold3d import Manifold

        post = Manifold.cylinder(40.0, BUMP_RADIUS, BUMP_RADIUS, 24)
        feet.append(post.translate([float(px[k]), float(py[k]), z - 20.0]))
    feet = S.add(feet) ^ touch

    # Everything is held back from the wall by the glue gap.  Built into a
    # cover, a web deliberately reaches OVERLAP into the wall so the two fuse
    # when printed as one body; a part glued in afterwards must not -- it would
    # simply not go in, and it did not: against the printed file it fouled by
    # 716 cubic millimetres, almost all of it that half millimetre round the
    # web's edge.
    room = S.core(surface, wall + GLUE_GAP, rows=rows)
    part = S.add([web ^ room, band ^ room, feet])

    # And clear of the thickening that runs down the inside of the printed
    # cover where the halves meet.  It is 9 mm deep there and 2.55 in what the
    # tab builds now, so the part has to be cut to the cover that exists, not
    # to the one the code would make today.  Only the outer band is taken
    # away: the bolt lugs sit far inside and are nowhere near it.
    printed_land = (S.curved_slab(seam.z_curve, seam.y_curve, PRINTED_LAND_HALF)
                    ^ S.band(surface, wall - 1.0, wall + PRINTED_LAND_DEPTH, rows=rows))
    part = S.sub(part, [printed_land])
    parts = part.decompose()
    part = max(parts, key=lambda m: m.volume()) if len(parts) > 1 else part

    OUT.mkdir(exist_ok=True)
    mesh = mb.from_manifold(part)
    # Both formats out of the one body, in one place.  Written separately once,
    # the 3MF was left behind by a fix the STL got and quietly carried a part
    # that fouled the cover by 716 cubic millimetres.
    written = []
    for fmt in ("stl", "3mf"):
        data = mesh.export(file_type=fmt)
        data = data if isinstance(data, bytes) else data.encode()
        if fmt == "3mf":
            from backend.export import paint_3mf
            from backend.params import MATERIALS_BY_KEY

            spec = MATERIALS_BY_KEY.get(params.material, MATERIALS_BY_KEY["teal"])
            data = paint_3mf(data, spec.hex, f"{spec.label} {spec.polymer}")
        path = OUT / f"glue-in-lower-web.{fmt}"
        path.write_bytes(data)
        written.append(path)

    arc_band = float(band.volume() / BAND_THICKNESS / BAND_HEIGHT * BAND_HEIGHT)
    print(f"the wall belongs at z = {z:.0f} mm above the bottom edge")
    print(f"part: {mesh.volume / 1000:.1f} cm3, {len(mesh.faces)} faces, "
          f"closed {mesh.is_watertight}, pieces {mesh.body_count}")
    print(f"  bonded area about {band.volume() / BAND_THICKNESS / 100:.0f} cm2 "
          f"(edge-on would be {arc_band / BAND_HEIGHT * 7.0 / 100:.0f})")
    for path in written:
        print(f"  written to {path}")


if __name__ == "__main__":
    main()
