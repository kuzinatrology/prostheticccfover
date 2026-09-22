"""What holds a cover on: a seam with magnets, and clamps on the pylon.

One module for both covers that have no attachment of their own -- the
anatomic shank and the Rhino model -- because neither draws its own silhouette
and both are stored the same way: a radius over angle and height about a centre
line.  Everything here works on that, so a cover is split, landed, magneted and
clamped without either tab knowing how the other does it.
"""

from .hardware import Hardware  # noqa: F401
