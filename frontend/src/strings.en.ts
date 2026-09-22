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

  /** The covers, one tab each. */
  tabs: {
    transtibial: "Below knee",
    transfemoral: "Above knee",
    anatomic: "Anatomic shank",
    iter1: "Iteration 1",
    iter2: "Iteration 2",
  } as Record<string, string>,

  /** The transfemoral tab's own words. Everything else is shared. */
  transfemoral: {
    masthead: {
      title: "Transfemoral cover",
      subtitle: "Capital knee · cosmetic shell, printed to order",
    },
    specKeys: {
      wall_thickness: "W",
      pattern_density: "D",
      irregularity: "I",
      anisotropy: "X",
      strut_width: "S",
      magnet_count: "M",
    } as Record<string, string>,
    bodies: {
      heading: "Parts",
      front: "Front half",
      back: "Back half",
      lower_clamp_back: "Lower clamp, back",
      upper_clamp_back: "Upper clamp, back",
    } as Record<string, string>,
    explode: "Pull the parts apart",
    downloadBody: "3MF",
  },

  /**
   * The anatomic tab's own words. This cover is not drawn by sliders: its
   * shape is measured off a scan of the prosthesis and off a human shank, so
   * the controls are tolerances and the shape of the rim, and the readout
   * that matters is how far the knee still bends.
   */
  anatomic: {
    masthead: {
      title: "Anatomic shank cover",
      subtitle: "Shaped from the prosthesis scan and a MakeHuman shank",
    },
    specKeys: {
      clearance: "C",
      wall_thickness: "W",
      knee_cover: "K",
      pattern_density: "D",
      irregularity: "I",
      strut_width: "S",
    } as Record<string, string>,
    flexionLabel: "Bends to",
    gapLabel: "Gap",
    jammed: "jams",
  },

  /** The reference tab: the same cover with its rim and silhouette traced. */
  reference: {
    masthead: {
      title: "Cover from the reference",
      subtitle: "Rim and silhouette traced off the two renders",
    },
    specKeys: {
      clearance: "C",
      wall_thickness: "W",
      seat_z: "Z",
      pattern_density: "D",
      strut_width: "S",
    } as Record<string, string>,
  },

  /**
   * The modelled tab's own words. This cover is the other way round from the
   * rest: its shape is a file someone drew, so there is nothing here that
   * shapes it. What the sliders do is give that shape a wall and a pattern.
   */
  iter1: {
    masthead: {
      title: "Modelled cover",
      subtitle: "cover ready iteration 1 \u00b7 wall and pattern on the Rhino model",
    },
    specKeys: {
      fullness: "F",
      wall_thickness: "W",
      pattern_density: "D",
      irregularity: "I",
      anisotropy: "X",
      strut_width: "S",
      rim_solid: "R",
    } as Record<string, string>,
    wallLabel: "Wall",
    modelLabel: "Model",
  },

  /**
   * The second modelled tab. The same kind of object as the first -- a Rhino
   * file with a wall and a pattern on it -- with the attachment the first one
   * has not: a seam with magnets and two clamps on the pylon. So it ships four
   * bodies rather than one, and the loose ones can be pulled off the cover in
   * the viewer.
   */
  iter2: {
    masthead: {
      title: "Modelled cover, fastened",
      subtitle: "Cover new \u00b7 split in halves, magnets on the seam, clamps on the pylon",
    },
    specKeys: {
      fullness: "F",
      wall_thickness: "W",
      pattern_density: "D",
      strut_width: "S",
      magnet_count: "M",
      clamp_count: "C",
      bolt_diameter: "B",
    } as Record<string, string>,
    wallLabel: "Wall",
    modelLabel: "Model",
  },

  groups: {
    limb: "Limb",
    section: "Section",
    shell: "Shell",
    pattern: "Cell field",
    relief: "Relief",
    mask: "Where",
    finish: "Finish",
    fit: "Fit",
    seat: "How it sits",
    silhouette: "Silhouette",
    rim: "Rim and notch",
    mount: "Attachment",
    leaves: "Leaves on the back",
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
    rim_solid: "Plain band at the rim",
    clearance: "Clearance",
    fullness: "Calf fullness",
    top_z: "Top of the rim",
    bottom_clearance: "Above the ankle",
    front_dip: "Front dip",
    notch_depth: "Back notch",
    seat_z: "Top of the cover",
    knee_cover: "Over the knee",
    flexion: "Must bend to",
    notch_deepen: "Notch deeper",
    height_scale: "Height",
    top_trim: "Rim lowered",
    bottom_trim: "Bottom raised",
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
    surface_smoothing: "Surface smoothing",
    seam_offset: "Seam back",
    seam_solid_width: "Plain band at seam",
    magnet_diameter: "Magnet diameter",
    magnet_height: "Magnet height",
    magnet_count: "Magnets per seam",
    lower_clamp_z: "Lower clamp height",
    upper_clamp_z: "Upper clamp height",
    lower_hole_diameter: "Tube hole",
    upper_hole_width: "Module hole, across",
    upper_hole_depth: "Module hole, front to back",
    bolt_diameter: "Bolt hole",
    clamp_count: "Clamps",
    leaf_count: "Leaves",
    leaf_size: "Leaf length",
    leaf_tilt: "Leaf lean",
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
    nut_kind: {
      label: "Bolt anchors",
      options: {
        heat_set: "Heat-set inserts",
        hex: "Captive nuts",
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
    back_leaves: "Large leaves instead of cells",
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
