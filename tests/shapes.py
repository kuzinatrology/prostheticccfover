"""Pictures the motif tests are made of.

Drawn here rather than committed as files, so the suite carries no binary and
every shape says in code what it is meant to exercise.
"""

from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw

SIZE = 400


def _square(d: ImageDraw.ImageDraw) -> None:
    d.rectangle([100, 100, 300, 300], fill=0)


def _circle(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([80, 80, 320, 320], fill=0)


def _ring(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([60, 60, 340, 340], fill=0)
    d.ellipse([140, 140, 260, 260], fill=255)


def _two(d: ImageDraw.ImageDraw) -> None:
    d.ellipse([40, 40, 180, 180], fill=0)
    d.ellipse([220, 220, 360, 360], fill=0)


def _tendril(d: ImageDraw.ImageDraw) -> None:
    """A disc with a whisker four pixels across, well under MIN_HOLE."""
    d.ellipse([120, 120, 280, 280], fill=0)
    d.rectangle([198, 280, 202, 392], fill=0)


def _crescent(d: ImageDraw.ImageDraw) -> None:
    """Not star shaped about any point in it: the cone-cap path cannot take it."""
    d.ellipse([40, 40, 360, 360], fill=0)
    d.ellipse([110, 110, 290, 290], fill=255)
    d.rectangle([200, 150, 400, 250], fill=255)


def _comb(d: ImageDraw.ImageDraw) -> None:
    """Prongs and gaps both narrower than a strut."""
    d.rectangle([60, 60, 340, 140], fill=0)
    for x in range(70, 340, 40):
        d.rectangle([x, 140, x + 18, 340], fill=0)


def _dumbbell(d: ImageDraw.ImageDraw) -> None:
    """Two masses on a bar thin enough for the opening to sever."""
    d.ellipse([40, 150, 180, 290], fill=0)
    d.ellipse([220, 150, 360, 290], fill=0)
    d.rectangle([170, 212, 230, 228], fill=0)


def _specks(d: ImageDraw.ImageDraw) -> None:
    """One shape and a great deal of dust around it."""
    d.ellipse([120, 120, 280, 280], fill=0)
    for x in range(40, 380, 30):
        for y in range(40, 380, 55):
            d.ellipse([x, y, x + 5, y + 5], fill=0)


def _star(d: ImageDraw.ImageDraw) -> None:
    points = []
    for k in range(10):
        r = 160 if k % 2 == 0 else 60
        a = math.pi * k / 5
        points.append((200 + r * math.cos(a), 200 + r * math.sin(a)))
    d.polygon(points, fill=0)


def _blank(d: ImageDraw.ImageDraw) -> None:
    """Nothing at all: a sheet of white paper."""


DRAWINGS = {
    "square": _square,
    "circle": _circle,
    "ring": _ring,
    "two": _two,
    "tendril": _tendril,
    "crescent": _crescent,
    "comb": _comb,
    "dumbbell": _dumbbell,
    "specks": _specks,
    "star": _star,
    "blank": _blank,
}


def png(name: str, size: int = SIZE) -> bytes:
    image = Image.new("L", (size, size), 255)
    DRAWINGS[name](ImageDraw.Draw(image))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def transparent(name: str, size: int = SIZE) -> bytes:
    """The same drawing as a cut-out, so the alpha branch gets exercised."""
    image = Image.new("LA", (size, size), (255, 0))
    mask = Image.new("L", (size, size), 255)
    DRAWINGS[name](ImageDraw.Draw(mask))
    image.putalpha(Image.eval(mask, lambda v: 255 - v))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def svg(name: str = "circle") -> bytes:
    return (
        b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
        b'viewBox="0 0 100 100"><circle cx="50" cy="50" r="34" fill="black"/></svg>'
    )
