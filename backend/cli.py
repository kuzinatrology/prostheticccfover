"""Command line front end for the generator.

    python -m backend.cli --out cover.3mf --pattern-density 0.7 --twist 12
    python -m backend.cli --image leaf.png --motif-fill 0.9 -o leaf.3mf

Writes a file and prints what the cover turned out to be. Everything the web
app can make, this can make.
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
import time

from .export import FORMATS, write
from .generator import DRAFT, FINAL, audit, generate
from .motif import LIBRARY
from .params import ENUMS, RANGES, CoverParams
from .presets import PRESETS, PRESETS_BY_KEY


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="backend.cli", description=__doc__)
    ap.add_argument("--out", "-o", default="cover.3mf", help="output file")
    ap.add_argument("--draft", action="store_true", help="coarse mesh, faster")
    ap.add_argument(
        "--preset",
        choices=[pr.key for pr in PRESETS],
        help="start from a preset; any option after it still wins",
    )
    defaults = CoverParams()
    for key, rng in RANGES.items():
        ap.add_argument(
            f"--{key.replace('_', '-')}",
            type=float,
            default=getattr(defaults, key),
            metavar=f"{rng.lo:g}..{rng.hi:g}{rng.unit}",
            help=f"default {getattr(defaults, key):g}",
        )
    for key, allowed in ENUMS.items():
        ap.add_argument(
            f"--{key.replace('_', '-')}", choices=list(allowed), default=None
        )
    ap.add_argument("--split-halves", action="store_true", help="cut down the seam")
    ap.add_argument(
        "--no-mask-mirror",
        dest="mask_mirror",
        action="store_false",
        default=None,
        help="put the masked panel on one side only",
    )
    ap.add_argument(
        "--image",
        metavar="FILE",
        help="cut the holes to the shape of this picture instead of the cells",
    )
    ap.add_argument("--seed", type=int, default=defaults.seed)
    return ap


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    out = pathlib.Path(args.out)
    fmt = out.suffix.lstrip(".").lower()
    if fmt not in FORMATS:
        print(f"choose one of {', '.join(FORMATS)} as the file extension", file=sys.stderr)
        return 2

    given = {a for a in argv or sys.argv[1:] if a.startswith("--")}
    values = CoverParams().to_dict()
    if args.preset:
        values.update(PRESETS_BY_KEY[args.preset].values)
    # A preset only sets what the command line has not: options still win.
    for key in RANGES:
        if f"--{key.replace('_', '-')}" in given or key not in values:
            values[key] = getattr(args, key)
    for key in ENUMS:
        if getattr(args, key) is not None:
            values[key] = getattr(args, key)
    if args.mask_mirror is not None:
        values["mask_mirror"] = args.mask_mirror
    values["split_halves"] = args.split_halves or values.get("split_halves", False)
    values["seed"] = args.seed
    if args.image:
        # The service holds an upload in memory; here the file is read once and
        # put in the same place, so both front ends run the same generator.
        try:
            values["motif_id"] = LIBRARY.add(pathlib.Path(args.image).read_bytes())
        except OSError as exc:
            print(f"cannot read {args.image}: {exc}", file=sys.stderr)
            return 2
        values["hole_shape"] = "image"
    params = CoverParams.from_dict(values)

    started = time.time()
    cover = generate(params, quality=DRAFT if args.draft else FINAL)
    faults = audit(cover)
    out.write_bytes(write(cover, fmt))

    m = cover.params.material_spec
    delta = cover.mass_g - cover.plain_mass_g
    weight = (
        f"{cover.saving_pct:.0f}% lighter than plain"
        if cover.saving_pct >= 0
        else f"{delta:+.0f} g heavier than plain"
    )
    print(f"{out}  {out.stat().st_size / 1e6:.1f} MB  {time.time() - started:.1f} s")
    print(f"  {m.label} {m.polymer}   {cover.mass_g:.1f} g   {weight}")
    print(
        f"  {cover.params.operation}   {cover.holes} holes   "
        f"{len(cover.mesh.faces)} triangles   wall up to {cover.max_wall:.1f} mm"
    )
    for note in cover.notes:
        print(f"  {note}")
    if faults:
        print("  MESH AUDIT FAILED: " + "; ".join(faults), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
