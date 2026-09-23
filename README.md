# Prosthetic cover configurator

A prototype web configurator for cosmetic covers. Four tabs, one per cover,
differing in where the shape comes from: **below knee** (transtibial, the
shape of the leg set by sliders), **above knee** (transfemoral, College Park
Capital knee, the shape taken from a scan of the other leg), **anatomic
shank** (built by the offline pipeline in `anatomic/` from the prosthesis scan
and a MakeHuman shank), and **iteration 1** (a cover modelled in Rhino and
handed to the configurator as a file). Move the sliders, watch the cover turn,
read its weight, download a print file. The transfemoral and the modelled tabs
have their own sections below; everything else here applies to all of them.

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

## Personal cabinet

The configurator now supports individual accounts. Open **Sign in / create
account** in the upper-right corner to register or sign in. The cabinet can
save the current parameter set under a name, reopen it later, and delete old
designs. Only the owner can delete a design; saved designs are publicly visible
in the community catalogue. If a design uses an uploaded image, the original
image bytes are stored with that design so it remains available after a server
restart.

For a deployed instance, set `COVER_SESSION_SECRET` to a long random value
before starting the service. The SQLite database is created at
`backend/configurator.sqlite3` and should be backed up with the rest of the
application data.

The **Community** button opens the public design catalogue. It includes every
saved design with its author nickname, a search by design name, visible 1–5
ratings, and a participant leaderboard based on average design rating. A user
can rate a design once and change that rating later.

Every nickname and design author links to `/profile/<user-id>`. Public profiles
show optional personal information, a year-long activity heatmap, and all of
the user's designs with their ratings. Profile fields are edited in the
owner's profile page; guests can only view them.

The profile avatar can be changed by clicking it and selecting an image. PNG,
JPEG, WebP and other Pillow-readable image files up to 2 MB are accepted. The
image is stored with the account and is also shown beside the nickname in the
header after sign-in.

The main screens have stable routes:

- `/workshop` — the cover configurator;
- `/profile/<user-id>` — a public user profile.

A saved design belongs to the tab it was drawn on. The tabs do not share a
parameter set -- the transtibial cover has no pylon diameter and Iteration 2 has
no calf bulge -- so each design records its tab and is read back through that
tab's own parameters. Opening a design from another tab reloads the page onto
that tab; in the catalogue such designs carry the tab's name beside them.

The header keeps **Workshop**, **Community**, and **Profile** in one responsive
navigation row. Guests also see **Sign in / Register**. After sign-in, that
button becomes the user's avatar and nickname and opens their profile; for a
guest, a profile is opened by clicking a user in Community or by visiting its
public URL.

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

## The transfemoral tab

`backend/transfemoral/` is a second pipeline beside the first. It shares the
cell field, the masks, the relief, the prisms, the motif reader and the
printer profile, and adds what a scan and a knee need. Nothing about the scan
or the knee reaches the interface: the person choosing sees the design
controls, a surface smoothing slider and an **Attachment** group.

```bash
.venv/bin/python -m tools.prepare_scan --render renders/stage_1   # once per scan
.venv/bin/python -m tools.stage_renders                          # stage renders + numbers
TF_EXAMPLES=20 .venv/bin/python -m pytest tests/test_transfemoral.py -q
```

### The scan

`tools/prepare_scan.py` reads `data/оболочка.stl` and writes
`backend/assets/leg_surface.npz` (radius over angle and height about a
centreline) and `leg_surface.json` (what each step found). Every step has a
flag. Mirroring is **off** for this file: it is already the mirrored copy of
the original scan, confirmed as the prosthetic side.

Front and back: the two indicators the brief names — the direction of the
largest radius over the calf and the drift of the section centres — agree to
6.4 degrees, and on this scan both point at the tibial crest, i.e. forward. A
shin section is long front to back and the crest reaches as far from the axis
as the calf does. They are used for the front-back line and for the
20-degree agreement check; which end is the back comes from two independent
cues that must agree: where the section's mass sits (the calf), and which way
the scan runs above the knee (the thigh). The blind spot then lands behind the
knee, as the brief says it should.

The knee axis sits over the last trusted section centre (z = 20), not on the
tangent carried up past it, which is the calf's forward drift into the knee
and would put the axis a centimetre in front of the joint.

Curvature is read over a 6 mm baseline: the scan's triangles are 8 mm across
and read point by point they have a 2 mm radius at every corner, which would
cap the wall and every hole at nothing.

**Evening out the knee.** Above z = 40 the probe rays start missing: the knee
is bent, the thigh shadows the back of it, and only a third of the ring is
seen behind the joint at z = 65. The gaps were filled, so rows two millimetres
apart came out up to eight millimetres apart, which showed as a wavy top rim
and a rippled surface over the whole upper third. `even_out_knee` builds the
surface **out** to a smooth envelope over it — dilate, then a 9 mm Gaussian
along the height and a 4 mm one around the section — faded in over 25 mm so
the shin below never moves, and capped at `KNEE_EVEN_MAX_SHIFT` (6 mm).

Out, never back, and the asymmetry is the whole point. Shaving the spikes
would even the rim just as well, but this surface is the cover's outer skin
and its wall goes inward from it, so a millimetre shaved here is a millimetre
off the room left for the knee module inside — and that clearance is thin
enough that three millimetres of shaving put the front half into the module on
several of the corpus's parameter sets. Filling can only add room. The price
is a knee up to 6 mm fuller, 0.8 mm on average. It runs before the smoothing
slider and whatever the slider says: these are the scan's shadows, not the
skin texture the slider is about. What is left rough is the hollow behind the
knee, which the notch cuts away. Below z = 40 nothing changes.

**Known limitation.** From z ≈ 20 up to `top_z` the scan is the knee bent to
114 degrees: the kneecap is displaced, the front is stretched, the outline is
not a straight knee's. It is the most visible part of the cover. The data
cannot correct it and straightening by rotation is worse. To be revisited with
a new scan.

### The notch

The cover is rigid and crosses a joint, so behind the knee it leaves free a
sector with its apex on the flexion axis at least as wide as the flexion. That
sector (grown by `notch_fillet`) is the notch, **together with** everything the
thigh stand-in sweeps through from 0 to `flexion_angle`, plus
`notch_clearance`. The sector alone does not clear the brief's own rotation
test: a leg-radius cylinder above the knee is wider than the shin in places,
and turning it sweeps its sides across the shin's side walls just below the
sector's lower edge. No sector can: it would need to open 106 degrees below
the horizontal and 88 above.

The thigh's radius is half the knee's width across, at the axis (56 mm), not
the mean radius at `top_z` (67 mm): that section is the bent knee with the
thigh and the filled blind spot in it, and a cylinder that size bit the front
half into a waist.

`notch_split` is 0.35, set from the first renders: at 0.5 the notch ran down
the calf almost to the ankle and left the back half a thin U.

Notch, seams and rims are fields over the unwrapped surface, in millimetres,
and they are what the pattern's mask is made of: rims and seams fade the cells
over 14 mm, the notch over 35 mm. A hole is then kept only if its whole outline
stays a strut from every edge.

Two more rules apply to this cover alone, because a fading cell erodes from its
rim inward and the last ones before the pattern stops come out as splinters
that pass `MIN_HOLE` and still read as chips in the edge rather than as holes.
A hole narrower than `MIN_TIDY_HOLE` (3 mm across, measured as the widest
circle it holds, in millimetres at its own place on the leg) is left solid; so
is one the fade is eating that is narrower than `TIDY_ASPECT` of its own
length. Outside the fade the shape rule never applies, so a design of
deliberately long cells keeps them. On the default cover the two together
leave 40 cells of 551 solid and the pattern ends on whole holes.

### Halves, magnets, clamps

The seams follow the centreline down each side, passing through the knee
axis at `seam_offset` = 0, and **both** end where the first of them runs into
the notch. The notch is a sector cut at an angle, so it crosses one seam tens
of millimetres below the other: on this scan at z = 7 and z = 57. Ended side
by side, the back half kept a tail between those two heights that narrowed
from a quarter of the turn to a point — a fin that prints badly, snaps easily
and reads as a mistake. Ending both together squares the back half off at
z = 7. `seam_offset` stops where the back half would keep less than a quarter
turn. Every half is a slab: a region of the surface between two offsets along
its normal, triangulated with interior points a chord apart and refined on the
surface.

The shelf under each seam is `magnet_diameter + CLEARANCE + 2 MIN_STRUT` wide
(the brief's width without the fitting gap leaves the strut beside the socket
short by half of it). The back half thickens inward under each socket; the
shelf sits deeper by that thickening plus the gap, so the back half slides
over it. Sockets are cylinders on one surface normal. The shelf breaks where
a clamp passes and gives way to the tube near the ankle; magnets are spread
along what is left.

A shelf that simply stopped left an 8 mm step in the outline of the half, once
per clamp, which is the first thing the eye finds on a part that is otherwise
a smooth curve. It now narrows into every break over `SHELF_RAMP` (14 mm) down
to `SHELF_STUB` (a quarter) of its width, so the step left is 2 mm rather than
8. Not to nothing: a shelf run out to a point would end in a wedge thinner
than a strut, which is what stopping it short was avoiding in the first place.
A magnet needs the shelf at full width under it, so it stands `SHELF_RAMP`
plus its own half width clear of a break rather than the half width alone.

Clamps sit on a line from the ankle's centre to the knee axis (7.5 degrees off
the scan's axis), at right angles to it. The tube is 30 mm; the module is
preliminary 60 × 65 mm (**neither is measured**: 65 is scaled off a
photograph, 60 is a guess), and its hole's defaults carry 2 mm extra. Ring,
lugs and ribs come from the room at that height and MIN_STRUT; a height where
they do not fit is not reachable, and the slider's track says so. The lower
clamp keeps out of the sector. The upper one cannot: it holds the module, and
the module itself stands in the sector, fixed to the shin, where no thigh ever
reaches.

### Output

Four bodies: front half (with shelves, sockets and both clamps' front parts),
back half, and the two clamps' back parts. Download all of them as a zip of
3MF (or STL) with their masses, or each on its own. The viewer mesh is
simplified to 0.3 mm, about a tenth of the print mesh's triangles.

### Tests

`tests/test_transfemoral.py` runs `tests/tf_properties.py` over random
attachment and design settings: every body closed; no vertex of a half in the
sector; the thigh turned from 0 to the flexion angle touches nothing; walls,
including behind every socket, at least MIN_STRUT (by rays through the mesh);
socket pairs on one axis; no body into another, the tube or the module; the
back parts of the clamps and the bolt heads at least CLEARANCE from the back
half; holes a strut from each other and from every edge. Counterexamples go
to `tests/regressions/tf_corpus.jsonl`. The first run found six, of four
kinds, all fixed: the rectangular hole's round corners clipping the module's
square ones; shelves running into the tube at the ankle; the notch read at
two depths when the swept thigh is not monotonic through the wall; and rays
through a shared mesh edge counted as a wall a hundredth of a millimetre thick.

## The modelled tab

`backend/iteration1/` is the other way round from every tab before it. The
first draws a cover from sliders, the second and third derive one from a scan;
this one is handed a cover that someone already modelled — `cover ready
iteration 1.stl`, exported from Rhino — and its job is to keep that shape, let
it be worn differently, and put a wall and a pattern on it. The design
controls are the shared ones; what is gone is every control that would draw a
silhouette from nothing.

```bash
.venv/bin/python -m backend.iteration1.prepare     # once per model file
.venv/bin/python -m pytest tests/test_iteration1.py -q
```

### Reading the file

`prepare.py` scatters three million points over the export's faces and bins
them by angle and height about a fitted centreline. In each cell the samples
split into two skins at the midpoint between the nearest and the farthest, and
each skin is the **mean** of its own samples: taking the extremes rings, since
the farthest of nine samples on a slanted triangle sits high by a fraction of
that triangle and which fraction depends on where the export's rows fell. The
result is `backend/assets/iteration1.npz` — outer radius, wall, coverage,
centreline and the two rim curves — and `iteration1.json`, what it found.

The file is a closed cover with a 4.9 mm wall, 462 mm tall, whose top rim runs
from 323 mm at the back of the knee to 457 at the sides. Read back, the stored
surface sits 0.01 mm from the model's outer skin at the median and 0.05 mm at
the 95th percentile, against triangles of the export that are millimetres
across.

Angles are stored over 0 to 2 pi, the range the surface reads them back in.
Stored over -pi to pi they would land outside the spline's knots for half the
turn and be extrapolated instead of read, and half the cover would come out
invented — which is what happened, and is what `test_the_stored_surface_is_the_modelled_one`
now holds down.

### Wearing the file differently

The shape is the file, but that is not the same as the shape being fixed. The
**Silhouette** and **Rim and notch** groups hold eight knobs, and every one of
them is a transformation of the measured surface rather than a shape of its
own: girth (`fullness`), the section squashed front to back or side to side
(`ovality`), how much of the swell is carried behind the axis
(`posterior_bias`), the turn between the two rims (`twist`), the cover
stretched along its axis (`height_scale`), and three cuts — `top_trim`,
`bottom_trim` and `notch_deepen`. So no slider can invent a cover the file
does not have: a fuller cover is this cover fuller.

They are applied to the section about its own centre in the transtibial
surface's order, so a design reads the same on this cover as on that one, and
the surface is cached on all eight together — moving a pattern slider re-reads
the same shaped surface instead of building it again.

`notch_deepen` is the one worth spelling out: it lowers the rim in proportion
to how much of a notch the rim already is at that angle, so the deepest point
moves by the whole slider and the high sides do not move at all. The trims
cannot make the two rims cross; a column is never left shorter than 30 mm.

### Starting points

The same six presets the other tabs offer — Lattice, Chevron, Scales, Vent,
Facet, Ridge — carried over by key through `backend/iteration1/presets.py`,
the way the transfemoral tab carries them. Every value in every one of them
survives the carry: a preset is made of design values, and this cover has all
of them. A preset moves the pattern and nothing else, so where the shape
sliders were left is where they stay.

### The rims

The two rim curves are what makes this cover different from a tube, and every
field that decides where material and holes may go is read from them rather
than from a grid: `edge_distance(u, v)` is the height to the nearer rim.
Cells fade out over 14 mm toward it, a plain band the **Plain band at the rim**
slider wide is left solid, and a hole is kept only if its whole outline stays
that band plus a strut clear. So the pattern ends on whole holes and the edge
is an edge.

### The wall

Laid down the radius, not along the normal. The cover is star shaped about its
axis and its walls stand within a few degrees of vertical, so a smaller radius
is what a wall inward means. Offsetting along the normal is what a general
solid would need and it is exactly what goes wrong here: over the rim the
normal turns up across the edge, and a skin offset along it climbs above the
rim and crosses the skin it came from — a rim of spikes. How much of the
normal is radial is divided back out so the wall measured across the skin is
the one the slider asks for; it is read a few millimetres inside the rim,
where the surface is the shape rather than the edge, and smoothed around the
section, because a wall that changes by a tenth of a millimetre per column is
a rippled rim band.

The slider starts on the wall the model was drawn with and reaches 8 mm rather
than the 4 mm the other tabs stop at: a range that could not reach the file's
own wall would refuse the model on the way in. Where the curvature of the
model binds first, the generator says so and the panel shortens the track.

### Output

One body, so one file: 3MF with the cover's colour, or STL. The plain shell
rebuilt from the grid holds 672 cm3 against the file's 676, the difference
being the wall measured across the skin rather than along the radius. A cut
pattern at the default density takes that to about 420 g in PETG, half the
plain weight, over roughly 3300 holes.

A draft takes about 20 seconds against 8 for the transfemoral tab and 5 for
the transtibial one. Nothing here is slower than those; the cover is simply
the largest surface in the app and carries the most cells, and most of the
time is in the shared pattern builder.

### Tests

`tests/test_iteration1.py` holds the two kinds of claim apart. That the tab
still describes the file: the stored surface is the model's skin, the rims are
the model's rims, the plain shell is the model's solid. And the claim every
tab makes: each operation gives one closed body, no hole opens onto a rim, the
wall measured by rays through the solid is the wall asked for, no setting at
the end of a range refuses a cover, and the smoothing slider never moves the
surface more than half a millimetre off the file.

## Out of scope

No topology optimisation, no FE, no accounts, no database, no
payments, no phone layout. The fields are the seam the first two would come in
through, and they are deliberately left open.

For an uploaded picture in particular: no background removal by a network, no
object recognition, no colour tracing, no contour editor in the browser. When
the automatic threshold misses on a photograph, the answer is the threshold
slider and the preview beside it.
