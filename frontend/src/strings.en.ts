/**
 * Every string the interface can show.
 *
 * Set any value to the empty string and the element it belongs to is not
 * rendered at all: no gap, no empty node, no markup change needed. That is
 * how labels get removed here, and it is why no component may hold a literal.
 */

export const strings = {
  masthead: {
    title: "Transtibial cover",
    subtitle: "Cosmetic shell, printed to order",
    specLabel: "Spec",
    specSeparator: " ",
    /** One letter per value on the spec line. Drop one and it leaves the line. */
    specKeys: {
      length: "L",
      knee_diameter: "K",
      ankle_diameter: "A",
      wall_thickness: "W",
      pattern_density: "D",
      irregularity: "I",
      anisotropy: "X",
      strut_width: "S",
    } as Record<string, string>,
  },

  presets: {
    heading: "Start from",
  },

  groups: {
    limb: "Limb",
    section: "Section",
    shell: "Shell",
    pattern: "Cell field",
    relief: "Relief",
    mask: "Where",
    finish: "Finish",
  },

  params: {
    length: "Length",
    knee_diameter: "Knee",
    ankle_diameter: "Ankle",
    calf_bulge: "Calf",
    calf_position: "Calf height",
    posterior_bias: "Calf to the back",
    ovality: "Ovality",
    section_squareness: "Squareness",
    twist: "Twist",
    wall_thickness: "Wall",
    pattern_density: "Density",
    density_gradient: "Gradient",
    irregularity: "Irregularity",
    anisotropy: "Stretch",
    flow_angle: "Lean",
    corner_radius: "Corners",
    strut_width: "Strut",
    motif_fill: "Fill",
    motif_rotation: "Turn",
    motif_rotation_jitter: "Turn spread",
    motif_scale_jitter: "Size spread",
    motif_smoothing: "Smoothing",
    threshold_bias: "Threshold",
    relief_depth: "Depth",
    mask_v_from: "From",
    mask_v_to: "To",
    mask_u_center: "Facing",
    mask_u_width: "Width",
    mask_feather: "Softness",
    facet_scale: "Facet size",
  } as Record<string, string>,

  /** Labels that change meaning when the hole is a picture rather than a cell.
   *  The slider underneath is the same one: a coarse cell field is a few big
   *  motifs and a fine one is many small ones, so only the word changes. */
  paramsImage: {
    pattern_density: "Motif size",
    irregularity: "Scatter",
  } as Record<string, string>,

  units: {
    mm: "mm",
    deg: "°",
    "": "",
  } as Record<string, string>,

  choices: {
    operation: {
      label: "Operation",
      options: {
        cut: "Cut through",
        emboss: "Raise",
        engrave: "Sink",
        none: "Smooth",
      } as Record<string, string>,
    },
    hole_shape: {
      label: "Hole shape",
      options: {
        cells: "Cells",
        image: "Image",
      } as Record<string, string>,
    },
    relief_profile: {
      label: "Shape",
      options: {
        dome: "Dome",
        ridge: "Ridge",
        bevel: "Bevel",
      } as Record<string, string>,
    },
    mask_mode: {
      label: "Pattern sits",
      options: {
        full: "Everywhere",
        band: "In a band",
        panel: "On a panel",
        stripes: "In stripes",
      } as Record<string, string>,
    },
    finish: {
      label: "Shading",
      options: {
        flat: "Flat",
        gradient: "Gradient",
        faceted: "Faceted",
      } as Record<string, string>,
    },
  } as Record<string, { label: string; options: Record<string, string> }>,

  toggles: {
    mask_mirror: "Repeat opposite",
    split_halves: "Split in halves",
    motif_align_flow: "Turn with the lean",
    motif_invert: "Cut the negative",
  } as Record<string, string>,

  motif: {
    choose: "Choose a picture",
    replace: "Choose another",
    hint: "PNG, JPEG, WebP or SVG. Up to 8 MB.",
    previewLabel: "Reading",
    reading: "Reading the picture",
    unreadable: "That file is not a picture this can read",
    empty: "Nothing stood out in that picture",
    /** Shown on the spec line, before the picture's short digest. */
    specTag: "IMAGE",
  },

  material: {
    heading: "Material",
    secondHeading: "Second colour",
    polymerSeparator: " · ",
    densityUnit: "g/cm³",
  },

  readout: {
    mass: "Weight",
    massUnit: "g",
    saving: "Lighter than plain",
    savingUnit: "%",
    added: "Heavier than plain",
    addedUnit: "g",
    holes: "Cells",
    triangles: "",
  },

  notes: {
    heading: "Notes",
  },

  actions: {
    download: "Download for printing",
    working: "Preparing",
    formatSecondary: "STL",
    formatHint: "3MF keeps the topology and the colour. STL is there when a tool insists.",
  },

  status: {
    computing: "Recalculating",
    offline: "Model service not reachable",
    draft: "Draft mesh",
  },
} as const;

/** Empty strings mean "do not render this". */
export function has(value: string | undefined): value is string {
  return typeof value === "string" && value.length > 0;
}
