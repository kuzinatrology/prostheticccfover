# Transtibial cover configurator

A prototype web configurator for cosmetic covers for a below-knee prosthesis.
Move the sliders, watch the cover turn, read its weight, download a print file.

The whole point of the build is the last mile: **a design that fails a
printability check is not reachable**. Every constraint is built into the
generator so no slider combination can produce one, and the interface never
tells anybody their design was rejected.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.app:app --port 8000     # geometry service
cd frontend && npm install && npm run dev                   # http://localhost:5173
```

`npm run build` puts the page in `frontend/dist`, and the service serves it
from the same port, so a built copy needs only the one process.

### Leaving it running

On macOS a launch agent keeps the service up, so the page is always at the same
address rather than only while a terminal is open:

The plist ships with a placeholder path in it; point it at wherever this is
checked out before loading it.

```bash
cp deploy/com.cover.configurator.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cover.configurator.plist
echo '127.0.0.1  cover.test' | sudo tee -a /etc/hosts   # http://cover.test:8000
```

`.test` rather than `.local`: macOS hands `.local` to Bonjour, and an
`/etc/hosts` entry there resolves only sometimes. `.test` is reserved for
exactly this and always does.

The agent binds `0.0.0.0`, so anybody on the same network opens it at
`http://<this machine's address>:8000`. That address comes from DHCP and can
move; reserve it on the router if it needs to stay put. `cover.test` is a line
in *this* machine's `/etc/hosts` and means nothing to anyone else's.

Nothing beyond the network is a boundary here: there is no sign-in, and every
rebuild is a couple of seconds of CPU with one worker behind it. Fine among
people who share a router, not something to put on the open internet as it
stands.

The agent has `RunAtLoad` and `KeepAlive`, so it starts at login and comes back
if it dies. It logs to `~/Library/Logs/cover-configurator.log`. To stop it,
`launchctl bootout gui/$(id -u)/com.cover.configurator`; to start it again,
`bootstrap` the same file. The port stays 8000 because binding 80 would mean
running the geometry service as root, which is not worth a shorter address.

Or skip the web app entirely:

```bash
.venv/bin/python -m backend.cli --preset chevron -o cover.3mf
.venv/bin/python -m backend.cli --image leaf.png -o leaf.3mf
.venv/bin/python -m backend.cli --operation emboss --relief-profile dome -o scales.3mf
.venv/bin/python -m backend.cli --help
```

Tests:

```bash
.venv/bin/python -m pytest tests -q
COVER_EXAMPLES=200 .venv/bin/python -m pytest tests -q      # a longer hunt
```

## The four axes

A design is not a list of pattern types. It is four independent things
multiplied together, and the variety comes from the product:

```
cell field (u,v)  x  operation  x  mask (u,v)  x  finish
```

**Cell field.** Where the cells are and what shape they are: density and its
gradient, irregularity, stretch, lean, corner rounding, strut width.

**Operation.** What is done with those cells. `cut` drives prisms through the
wall and removes them. `emboss` and `engrave` displace the outer surface and
touch no boolean at all. `none` leaves the shell smooth.

**Mask.** Where the pattern lives: everywhere, in a band, on a panel front and
back, or in stripes. The edge is feathered, and that feathering is the point:
a hard edge reads as a cropped picture, a soft one reads as a designed object.

**Finish.** How it is shaded in the viewer. Flat, a gradient between two
palette colours, or faceted. None of it touches the mesh, so weight and print
file are identical across all three.

Six presets in `backend/presets.py` are starting points on those axes. Picking
one moves the sliders and lets go: nothing is locked afterwards, and the strip
stops marking a preset the moment the design has moved off it.

### The hole can be a picture

`samples/` holds a few drawings to try it on, written out of `tests/shapes.py`:
a ring whose middle would fall out, a comb whose prongs are narrower than a
strut, a disc with a whisker four pixels across.


`HOLE SHAPE: [CELLS] [IMAGE]` is not a fifth axis. Upload a leaf, a logo, a
silhouette, and it decides what a hole *looks like*; the cell field still
decides where the holes are and how big. So there is no new slider for "one
big motif or many small ones" — that is the density slider, relabelled, and
the mask, the gradient, the stretch and the lean all keep working untouched.

`backend/motif.py` reads the file. The alpha channel is believed where there
is one, because a cut-out carries its own silhouette and no threshold beats
it; otherwise Otsu's method splits the histogram and `threshold_bias` slides
that split, since on a photograph the automatic answer is often a little off
and this is the only way to put it right by hand. Whatever runs around the
border of the picture is the background. Marching squares traces the contours,
nesting sorts outlines from holes, and what comes out is a polygon in the unit
square. The file stays in memory for the session; the design carries only its
digest, which is also what goes on the spec line so the same picture and the
same sliders rebuild the same cover.

The panel shows the silhouette it read, beside the drop zone, before anything
is cut. That preview is the feature, not an ornament: without it the upload is
a black box, a cover comes back carrying something that does not look like the
picture, and there is no way to tell whether the threshold missed or the file
was wrong.

## How the geometry is put together

`backend/surface.py` builds the outer surface. The section is a superellipse,
so its sides can flatten, and its centre slides backward where the calf swells,
so the calf grows behind while the front of the shank stays where it was. The
section is walked at **equal arc length** rather than equal angle: a
superellipse parameterised by angle races through the ends of its axes, which
would stretch every cell sitting near one.

`backend/fields.py` holds the scalar fields. Density and mask are the same kind
of object, a function of (u, v) returning a number in [0, 1].

`backend/pattern.py` lays out the cells in a conformal ("Mercator") image of
the cover, `U = 2πu` and `V = ∫L dv/r(v)`, where the metric is
`r(v)²(dU² + dV²)`. A round cell there is a round cell on the cover, and cells
grow with the cover's girth.

Stretch and lean add one layer on top: seeds are laid out in a *lattice* space
and carried into the domain by a linear warp with determinant one. Cell areas
survive it, so cell counts do; adding a full turn to `U` is a pure shift in
that space, so the seam still closes however far the pattern leans; and the
cells are carried into the domain *before* anything is measured, so no
printability rule ever sees the warp.

`backend/relief.py` is the whole of emboss and engrave. For a Voronoi diagram
the distance to a cell boundary is exactly half the gap between the two nearest
seeds, so two nearest-neighbour queries give the height everywhere, and the
shell is built from a displaced grid.

`backend/mesh_build.py` closes a solid between any two grids, drives a prism
through the wall for every hole, and removes them all with one `manifold3d`
boolean. `backend/generator.py` ties it together and produces the notes.

Two details in the prisms earn their keep. A prism's caps are flat while the
wall is curved, so each cap is laid on the surface and subdivided until no
triangle outruns the curvature; without it the middle of a wide hole keeps a
lens of material floating free of the cover. And a prism's side wall is a
straight chord where the hole's edge is really a curve, so it bows into the
strut: long edges are split until that bow is small, and the remainder is paid
back in the erosion.

A cell's own hole is convex, and a cone of triangles from its centre is the
cheapest cap that covers it. A motif's hole is whatever the picture was, and a
cone from any single point folds over itself on a shape like a letter C. Those
caps are triangulated instead — a constrained Delaunay triangulation fills the
ring exactly, using the ring's own vertices, then red-green refinement splits
it until no edge outruns the same chord. Which builder a ring goes to is read
off the ring, so the cell field's own output is built exactly as it was
before, and a motif that happens to be convex costs nothing extra.

### The density field

Pattern density is a **function**, not a number:

```python
def build_cells(surface, density: Callable[[float, float], float], ...)
```

The two sliders build one. So does the mask, which is the same kind of object
used at a different point. A stress field from an FE run, or a mask painted in
the interface, is a one-line change in `fields.py`; nothing under it ever sees
a scalar.

### Irregularity

One code path covers both ends of the slider. A graded hexagonal lattice is
built from the spacing field, every node is displaced by `irregularity` times a
random offset, and the variable disk radius is then enforced directly by
pushing apart any pair that ended up too close. At 0 the lattice is untouched;
at 1 the nodes are as scattered as the spacing allows. Two damped relaxation
passes absorb the seams where the lattice has to change its column count — a
clean lattice is a fixed point of that operation, so the ordered end stays
ordered.

## The guarantees, and where each one lives

| Rule | How it cannot be broken |
|---|---|
| Strut ≥ `MIN_STRUT` | The hole *is* the cell eroded by `strut/2`, measured in mm at the cell's tightest scale. There is nothing to check. |
| Cell too small to erode | Erosion returns empty, the cell stays solid. Silently. |
| Hole < `MIN_HOLE` | Inscribed radius via `polylabel`; below the limit the cell stays solid. Silently. |
| Hole > `a_max` | The cell's seed is replaced by three and the neighbourhood is rebuilt finer. The pattern gets smaller there, not different. |
| Corner rounding | An opening (`buffer(-r).buffer(+r)`) can only take material away, so no rule needs re-checking after it. |
| Mask feathering | Fading the mask deepens the same erosion. Half a mask is half a cell gone, whatever the cell's size, and a mask at zero closes it completely. |
| Wall vs curvature | `wall_thickness`'s upper bound is recomputed from the surface's smallest radius of curvature and sent to the panel, which shortens the slider's track. |
| Groove vs wall | `relief_depth`'s upper bound is 60% of the wall when engraving, by the same moving-track mechanism. Embossing has no ceiling: it removes nothing. |
| One connected piece | Voronoi edges form a connected graph, so the shell cannot fall apart. Confirmed by genus: it comes out at exactly one per hole plus one for the tube. |
| Mesh edges eating the strut | Ring edges are split until their bow is under a fixed fraction of the strut, and the erosion is widened by exactly that fraction. |
| A picture's own thin details | The motif is opened by `MIN_HOLE/2`. An opened shape is a union of discs of that radius, so nothing in it can be thinner. |
| A picture's own thin gaps | The motif is then closed by `strut/2`. The complement of a closed shape is a union of discs, so no gap in it can be narrower. |
| A motif wider than the wall | Its own fill is cut back in that cell and it is laid again. Subdividing is for cells; half a leaf is not a leaf. |
| A hole inside a hole | Filled. It is a disc of shell with nothing holding it, and it would drop out of the print. |

`a_max` is `STIFFNESS_C · t^1.5` (a plate deflects as span² and stiffens as
t³), capped by the bridging limit relaxed by an arch factor, and capped again
at 90% of the surface's radius of curvature so a hole cannot outgrow the wall
it is cut through. A squarer section curves harder at its corners, so it gets
a finer pattern; that is the physics, not a rule bolted on.

Every millimetre-to-domain conversion is **measured from the surface**, not
guessed from the section's half-widths. That was an ellipse-only shortcut, and
it stopped being an upper bound the moment the section could be a superellipse.

When something does move, the panel says so as a property of the object —
`Struts widened to 0.8 mm`, `Relief held at 1.4 mm by the wall`, `Pattern
refined across 12 cells for stiffness`, `Thin details below 1.5 mm removed`,
`Using 12 largest shapes of 47`. The words "error", "invalid" and "failed"
appear nowhere in the interface.

There is one check in the codebase, `generator.audit`, and it is aimed at us:
watertight, consistent winding, expected body count, positive volume, and for
a solid operation the topology of a plain tube. It runs before any file is
written. A failure is a generator bug and is logged with the full parameter
set. The user still gets their file.

## Printer profile

`backend/printer_profile.py` holds every calibration constant. **The values
are preliminary** — educated starting points for a 0.4 mm nozzle — and are
meant to be replaced after a calibration print: a plate of struts 0.4–1.6 mm,
holes 1.0–4.0 mm, and a three-point bend coupon at each wall thickness.
`PrinterProfile` is a dataclass so several can coexist.

## Weight

Weight is shown against the same shape left plain. Cutting takes material away
and the panel reads `77 % lighter than plain`; raising a relief puts material
on and the same line reads `+154 g heavier than plain`. One reference, two
wordings, chosen by the sign.

## Tests

`pytest` drives `hypothesis`, which picks the parameters across every
operation, every mask mode and every range. The properties:

1. Closed, correctly wound, and in one piece — two when a split was asked for.
2. Struts at least `MIN_STRUT` wide.
3. No hole wider than `a_max`.
4. No hole below `MIN_HOLE`.
5. Positive volume, and below the plain volume wherever material was removed.
6. In a solid operation, nothing goes through the wall: the cover is still one
   tube with an opening at each end and no other hole in it.
7. An engraved groove never leaves the wall below 40% of itself.
8. A masked panel keeps the pattern inside its own angular width.
9. All six presets build, pass everything above, and export.

`tests/test_motif.py` states them again for an uploaded picture, over shapes
picked to break each one: a whisker four pixels across, a comb whose prongs and
gaps are both narrower than a strut, a dumbbell whose bar the opening severs, a
crescent no cone of triangles can cover, a ring whose middle would fall out,
and a sheet of white paper. The pictures are drawn in `tests/shapes.py` rather
than committed, so the suite carries no binary and every shape says in code
what it is there to break.

The measurements come from `backend/measure.py`, which works on the real 3D
positions of the hole boundaries and probes the wall by firing rays at the
finished mesh, rather than reusing the generator's own arithmetic. A mistake in
that arithmetic cannot hide behind a test that shares it.

Anything that fails is appended to `tests/regressions/corpus.jsonl` and re-run
from then on, a few cases per kind of failure so the suite stays quick. Five
bugs went in that way, each one caught by the engine rather than by hand:

1. Flat prism caps left a lens of material floating inside every wide hole.
2. Cutting the seam shed strut fragments that belonged to neither half.
3. On a slim cover the hole span outgrew the curvature and the prisms drove
   into the opposite wall.
4. Straight mesh edges bowed into the struts from both sides and met in the
   middle, cutting a strut the pattern had sized correctly.
5. On a superellipse section the millimetre-per-domain-unit bound stopped
   being a bound, and holes came out wider than the wall could carry.

The last two are the reason the corpus is worth keeping. Every property held on
the ideal geometry; only the built object was wrong.

## Interface

`frontend/src/strings.en.ts` holds every visible string. **An empty string
means the element is not rendered at all** — no gap, no empty node, no markup
change. `readout.triangles` ships empty as a demonstration: the triangle count
simply is not there. The rule holds for controls too, so clearing the download
label removes the button rather than leaving a blank slab of colour.

The page is an orthopaedic order form: a narrow column of label-and-value rows
over the model. The hairline rules that separate the rows *are* the sliders, so
the one saturated thing on the page — the colour of the cover — runs along the
form's own structure. Picking a material recolours the tracks, the thumbs, the
choice strips, the note marks and the download button. Weight and the balance
against a plain cover sit in the sticky footer, where an order form puts its
total. Rows that the current operation has nothing to say about are hidden
rather than greyed.

`frontend/src/presets.ts` holds only the drawings on the preset tiles: small
deterministic pictures of what each one does, in the shape of a cover. The
values themselves come from the server.

Dragging a slider requests a draft mesh after 250 ms; releasing it requests the
full one. Changing the finish requests nothing at all — it is shading, and the
browser does it. Auto-rotation stops on first touch and never starts under
`prefers-reduced-motion`.

## Known limits

- Rebuild time is one to three seconds over most of the range. The far corner —
  longest, widest, thinnest wall, densest pattern, about 3300 holes — takes
  about five, which misses the two-second target and is stated here rather than
  hidden. Most of it is the boolean. The obvious next move is to keep the shell
  and re-cut only the cells a change touched.
- The graded hexagonal lattice follows density along `v` only. A density field
  that varies around the circumference is honoured by the jitter and the
  spacing, but not by the lattice's column count, so a `u`-varying field at
  `irregularity = 0` will be approximate.
- The dynamic ceiling on `wall_thickness` is real but rarely binds inside the
  declared ranges. The mechanism is there for wider ranges and for
  scan-driven surfaces later; its narrowed track has been exercised. The
  ceiling on `relief_depth` binds routinely.
- Corner rounding is scaled by the hole's own inscribed radius rather than by
  the printer's minimum strut, which the brief suggested. At real cell sizes
  the latter is invisible.
- Faceting bins triangles into hexagons on the surface and averages their
  normals. The mesh is untouched, as specified, so facet edges follow the
  underlying triangulation and are slightly ragged up close.
- A picture only reaches the geometry under `cut`. Raising and sinking read the
  cell field directly, without ever building a polygon, which is what makes
  them fast; a motif there would mean a second relief path for one operation.
- An SVG is rasterised at the working size and traced like everything else,
  rather than having its paths imported. At 512 pixels under the smoothing
  slider the difference does not survive to the print, and it keeps one code
  path instead of two.
- The picture lives in memory for the life of the process, eight uploads at a
  time. A design opened later still carries the digest but not the file, and
  falls back to cells with a note saying so.
- Printability was verified by round-tripping 3MF and STL back through trimesh
  (watertight, consistent winding, expected body count, matching volume, and
  the colour written as a 3MF base material). It has not been through a slicer
  or a printer.

## Out of scope

No topology optimisation, no FE, no leg scans, no accounts, no database, no
payments, no phone layout. The fields are the seam the first two would come in
through, and they are deliberately left open.

For an uploaded picture in particular: no background removal by a network, no
object recognition, no colour tracing, no contour editor in the browser. When
the automatic threshold misses on a photograph, the answer is the threshold
slider and the preview beside it.
