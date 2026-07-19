// SARA 2026 slide deck: "Lowering the Barrier to Radio Astronomy"
// Content source: reports/haswell-2026-07/DSES_Haswell_Trip_Report_2026-07.docx
// (the hand-tuned master; text ported, not auto-extracted).
//
// Run:  NODE_PATH=<dir with pptxgenjs> node build_deck.js
// Output: Lowering_the_Barrier_to_Radio_Astronomy_SARA_2026.pptx (same folder)

const path = require("path");
const pptxgen = require("pptxgenjs");

// ---------- DSES palette (from Administration/DSES Logo Variants/README.txt) ----
const NAVY = "0A2F40"; // deep-space navy — dark slide bg, headings
const TEAL = "156082"; // DSES document teal — primary
const GOLD = "B86A18"; // "the dish at dusk" — accent
const GOLD_SOFT = "D99C55"; // gold readable on navy
const ICE = "B8D2DE"; // subdued text on navy
const RING = "2E5A70"; // arc rings on navy
const INK = "24343C"; // body text on white
const MUTED = "6B7A82"; // captions, footers
const TINT = "EFF4F7"; // card background
const TINT_LN = "D7E3EA"; // card border
const WHITE = "FFFFFF";

const HEAD = "Cambria";
const BODY = "Calibri";

// ---------- assets -------------------------------------------------------------
const A = (...p) => path.join(__dirname, ...p);
const LOGO_TEAL = A("..", "assets", "DSES_Logo_Compact_Teal.png"); // 1317x488
const LOGO_REV = A("..", "assets", "DSES_Logo_Compact_Reversed_WhiteOnNavy.png"); // 1457x598, card is NAVY
const FIG_0329R = A("figures", "B0329+54_prepfold_gapbridged.png"); // 1542x1087, 2026-07-17 re-fold
const FIG_0950 = A("..", "haswell-2026-07", "figures", "B0950+08_prepfold.png"); // 1637x1157
const APP_ICON = A("..", "..", "icons", "dses_sa.png"); // square, pulsar art

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pptx.author = "Richard M. Hambly (K0GD)";
pptx.company = "Deep Space Exploration Society";
pptx.title = "Lowering the Barrier to Radio Astronomy";

const W = 13.333;
const MX = 0.62; // left margin

let pageNo = 0;

// ---------- helpers -------------------------------------------------------------
function lightSlide(kicker, title, titleW) {
  const s = pptx.addSlide();
  s.background = { color: WHITE };
  pageNo++;
  s.addText(kicker.toUpperCase(), {
    x: MX, y: 0.38, w: 9.5, h: 0.3, margin: 0,
    fontFace: BODY, fontSize: 11, bold: true, color: TEAL, charSpacing: 2,
  });
  s.addText(title, {
    x: MX, y: 0.66, w: titleW || 10.4, h: 0.75, margin: 0,
    fontFace: HEAD, fontSize: 29, bold: true, color: NAVY,
  });
  s.addImage({ path: LOGO_TEAL, x: 11.52, y: 0.42, w: 1.2, h: 0.445 });
  s.addText("Lowering the Barrier to Radio Astronomy  •  DSES  •  SARA 2026", {
    x: MX, y: 7.08, w: 6.5, h: 0.25, margin: 0,
    fontFace: BODY, fontSize: 8.5, color: MUTED,
  });
  s.addText(String(pageNo), {
    x: 12.55, y: 7.08, w: 0.5, h: 0.25, margin: 0, align: "right",
    fontFace: BODY, fontSize: 8.5, color: MUTED,
  });
  return s;
}

function darkRings(s, cx, cy) {
  for (const r of [0.85, 1.65, 2.45, 3.25, 4.05]) {
    s.addShape(pptx.ShapeType.ellipse, {
      x: cx - r, y: cy - r, w: 2 * r, h: 2 * r,
      fill: { color: NAVY, transparency: 100 },
      line: { color: RING, width: 1 },
    });
  }
}

function card(s, x, y, w, h, fillColor, lineColor) {
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.08,
    fill: { color: fillColor || TINT },
    line: { color: lineColor || TINT_LN, width: 0.75 },
  });
}

function stat(s, x, y, w, big, label, color) {
  card(s, x, y, w, 1.62);
  s.addText(big, {
    x: x + 0.15, y: y + 0.12, w: w - 0.3, h: 0.85, margin: 0, align: "center",
    fontFace: HEAD, fontSize: 34, bold: true, color: color || TEAL,
  });
  s.addText(label, {
    x: x + 0.15, y: y + 0.95, w: w - 0.3, h: 0.58, margin: 0, align: "center", valign: "top",
    fontFace: BODY, fontSize: 11.5, color: INK,
  });
}

function numDot(s, x, y, n, fillColor, d) {
  const dia = d || 0.42;
  s.addText(n, {
    shape: pptx.ShapeType.ellipse, x, y, w: dia, h: dia, margin: 0,
    fill: { color: fillColor || TEAL }, line: { color: fillColor || TEAL, width: 0 },
    align: "center", valign: "middle",
    fontFace: BODY, fontSize: dia >= 0.5 ? 18 : 14, bold: true, color: WHITE,
  });
}

function figFrame(s, imgPath, x, y, w, h) {
  s.addShape(pptx.ShapeType.rect, {
    x: x - 0.06, y: y - 0.06, w: w + 0.12, h: h + 0.12,
    fill: { color: WHITE }, line: { color: TINT_LN, width: 1 },
    shadow: { type: "outer", color: "9AACB5", blur: 6, offset: 2, angle: 90, opacity: 0.35 },
  });
  s.addImage({ path: imgPath, x, y, w, h });
}

// =================================================================================
// 1 — TITLE (dark)
// =================================================================================
{
  const s = pptx.addSlide();
  s.background = { color: NAVY };
  pageNo++;
  const cx = 11.15, cy = 2.35;
  darkRings(s, cx, cy);
  s.addImage({ path: APP_ICON, x: cx - 0.62, y: cy - 0.62, w: 1.24, h: 1.24, rounding: true });

  s.addText("SOCIETY OF AMATEUR RADIO ASTRONOMERS  •  2026 CONFERENCE", {
    x: 0.75, y: 1.15, w: 9.2, h: 0.35, margin: 0,
    fontFace: BODY, fontSize: 12.5, bold: true, color: GOLD_SOFT, charSpacing: 2,
  });
  s.addText("Lowering the Barrier\nto Radio Astronomy", {
    x: 0.72, y: 1.75, w: 9.4, h: 2.3, margin: 0,
    fontFace: HEAD, fontSize: 47, bold: true, color: WHITE, lineSpacing: 56,
  });
  s.addText(
    "First pulsar detections with the DSES Spectrum Analyzer — 60-foot dish, Haswell, Colorado",
    {
      x: 0.75, y: 4.25, w: 8.6, h: 0.75, margin: 0,
      fontFace: BODY, fontSize: 17, color: ICE,
    }
  );
  s.addText(
    [
      { text: "Richard M. Hambly (K0GD)", options: { bold: true, color: WHITE } },
      { text: "   •   Deep Space Exploration Society", options: { color: ICE } },
    ],
    { x: 0.75, y: 5.15, w: 9.0, h: 0.4, margin: 0, fontFace: BODY, fontSize: 15 }
  );
  // Reversed logo card is exactly NAVY, so it blends into the background.
  s.addImage({ path: LOGO_REV, x: 0.68, y: 6.1, w: 2.5, h: 1.026 });
  s.addNotes(
    "Title. One sentence framing: this is the story of a deliberate experiment — can we make " +
      "pulsar observing something any motivated DSES member can do, not just our two experts? " +
      "Field session July 11, 2026 at the Haswell, Colorado 60-foot dish; results verified over the following two days."
  );
}

// =================================================================================
// 2 — ABSTRACT
// =================================================================================
{
  const s = lightSlide("For the SARA program", "Abstract");
  card(s, MX, 1.62, 8.55, 5.15, WHITE, TINT_LN);
  s.addText(
    "For years, pulsar observing at the Deep Space Exploration Society has rested on a professional " +
      "toolchain — PRESTO and TEMPO built from source, custom GNU Radio flowgraphs, SIGPROC utilities, " +
      "and companion analysis tools — with a learning curve steep enough that only two members could take " +
      "an observation from dish to detection. This talk describes a deliberate experiment in lowering that " +
      "barrier. DSES developed the Spectrum Analyzer, a cross-platform application that consolidates the " +
      "on-site workflow — planning the observation, choosing clean frequencies, verifying the RF path, and " +
      "recording analysis-ready SIGPROC filterbank data — into a single, easy-to-use package driving an " +
      "Ettus USRP B210 software-defined radio. On July 11, 2026, a three-member team, none of them " +
      "pulsar-processing experts, put the premise to the test at the Society’s 60-foot dish in Haswell, " +
      "Colorado. B0329+54 was ultimately detected at 28 sigma — a figure that grew from 20 when peer review " +
      "of the trip report exposed, and repaired, a subtle recording-timebase defect — and B0950+08 produced " +
      "a strong ~9-sigma candidate whose best-fit period and dispersion land on the catalog values. Field " +
      "feedback drove two software releases within a week, and a documented upgrade queue — from a built-in " +
      "pulsar visibility planner to one-click post-recording analysis — now charts the path to training a " +
      "new generation of DSES observers on a far gentler learning curve.",
    {
      x: MX + 0.3, y: 1.9, w: 7.95, h: 4.6, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 13.5, color: INK, lineSpacingMultiple: 1.12,
    }
  );
  // At-a-glance column
  const gx = 9.5, gw = 3.2;
  card(s, gx, 1.62, gw, 5.15);
  const rows = [
    ["Speaker", "Richard M. Hambly, K0GD"],
    ["Society", "Deep Space Exploration Society (DSES), Colorado"],
    ["Instrument", "60-ft dish + Ettus USRP B210 SDR"],
    ["Software", "DSES Spectrum Analyzer + PRESTO"],
    ["Keywords", "pulsars • SDR • filterbank • accessibility"],
  ];
  let ry = 1.92;
  for (const [k, v] of rows) {
    s.addText(k.toUpperCase(), {
      x: gx + 0.25, y: ry, w: gw - 0.5, h: 0.26, margin: 0,
      fontFace: BODY, fontSize: 10, bold: true, color: TEAL, charSpacing: 1.5,
    });
    s.addText(v, {
      x: gx + 0.25, y: ry + 0.26, w: gw - 0.5, h: 0.62, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 12, color: INK,
    });
    ry += 0.97;
  }
  s.addNotes(
    "This abstract is what goes to the SARA meeting planner. Read silently in rehearsal, skip live — " +
      "or show for a beat while introducing the talk."
  );
}

// =================================================================================
// 3 — THE PROBLEM
// =================================================================================
{
  const s = lightSlide("The problem", "Pulsar observing had become an experts-only craft");
  s.addText(
    [
      { text: "For years the Society’s results rested on two members — ", options: {} },
      { text: "Dr. Richard Russel (AC0UB)", options: { bold: true } },
      { text: " and ", options: {} },
      { text: "Dan Layne (AD0CY)", options: { bold: true } },
      { text: " — and the professional toolchain they mastered:", options: {} },
    ],
    { x: MX, y: 1.58, w: 8.5, h: 0.65, margin: 0, fontFace: BODY, fontSize: 14, color: INK }
  );
  const tools = [
    ["PRESTO v5 + TEMPO1 + TEMPO2", "built from source; hand-edited observatory and clock files"],
    ["RIPTIDE", "a second, independent pulsar-search code (fast-folding)"],
    ["GNU Radio", "custom filterbank flowgraphs driving the B210"],
    ["SIGPROC", "filterbank-format utilities"],
    ["blimpy / watutil", "Breakthrough Listen RFI and saturation checks"],
    ["PINT", "high-precision pulsar timing in Python"],
    ["ATNF pulsar catalogue", "ephemeris data (.par) for every fold"],
    ["Murmur + Best Profile Analyzer", "I0NAA planning/analysis tools — run under Wine"],
    ["Stellarium + experience", "above all, knowing how the pieces fit together"],
  ];
  const gpx = 0.18, gpy = 0.16, tx0 = MX, ty0 = 2.3;
  const tw = (8.72 - 2 * gpx) / 3, th = 1.18;
  tools.forEach(([name, desc], i) => {
    const x = tx0 + (i % 3) * (tw + gpx);
    const y = ty0 + Math.floor(i / 3) * (th + gpy);
    card(s, x, y, tw, th);
    s.addText(name, {
      x: x + 0.18, y: y + 0.1, w: tw - 0.36, h: 0.3, margin: 0,
      fontFace: BODY, fontSize: 11.5, bold: true, color: NAVY,
    });
    s.addText(desc, {
      x: x + 0.18, y: y + 0.42, w: tw - 0.36, h: 0.7, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 10, color: INK,
    });
  });
  // The wider professional world uses even more — subdued: not even in OUR experts' stack
  card(s, tx0, 6.36, 8.72, 0.56, "F7FAFB", "E5EDF1");
  s.addText(
    [
      { text: "PSRCHIVE", options: { bold: true, color: MUTED } },
      {
        text: "  —  the professional community’s archiving & timing suite, in common use — beyond even our experts’ stack",
        options: { color: "93A2AA" },
      },
    ],
    { x: tx0 + 0.22, y: 6.36, w: 8.72 - 0.44, h: 0.56, margin: 0, valign: "middle", fontFace: BODY, fontSize: 11 }
  );
  // right stats
  stat(s, 9.6, 2.42, 3.1, "100s", "of pages of DSES training material for this stack", GOLD);
  stat(s, 9.6, 4.32, 3.1, "2", "members who could run an observation end to end", TEAL);
  s.addText("First-rate results — but a learning curve that kept everyone else watching.", {
    x: 9.6, y: 6.12, w: 3.1, h: 0.7, margin: 0, valign: "top",
    fontFace: BODY, fontSize: 11.5, italic: true, color: MUTED,
  });
  s.addNotes(
    "Credit where due: this toolchain produces first-rate, professional results, and Rich and Dan built " +
      "DSES's pulsar program on it. The point is not that the tools are bad — it's that the barrier to entry " +
      "kept hands-on observing limited to two people. Hundreds of pages of training material is a real number — " +
      "this tool list is straight from the DSES pulsar training guide's system-configuration table. " +
      "The grayed row is the kicker: the professional world in common use runs even deeper — PSRCHIVE is a " +
      "whole additional suite our two experts didn't even need."
  );
}

// =================================================================================
// 3b — THE NEW STACK (same chip format — deliberately near-empty)
// =================================================================================
{
  const s = lightSlide("The answer", "The new stack — much simpler");
  s.addText(
    "The same observation today takes two pieces:",
    { x: MX, y: 1.58, w: 8.5, h: 0.4, margin: 0, fontFace: BODY, fontSize: 14, color: INK }
  );
  // two chips + flow arrow, same card format as the previous slide
  const cw = 3.85, chh = 1.9, cy = 3.15;
  s.addText("ACQUISITION — ON SITE", {
    x: MX, y: cy - 0.42, w: cw, h: 0.3, margin: 0,
    fontFace: BODY, fontSize: 10, bold: true, color: TEAL, charSpacing: 1.5,
  });
  card(s, MX, cy, cw, chh);
  s.addText("DSES Spectrum Analyzer", {
    x: MX + 0.22, y: cy + 0.16, w: cw - 0.44, h: 0.34, margin: 0,
    fontFace: BODY, fontSize: 14.5, bold: true, color: NAVY,
  });
  s.addText("plan, survey, verify, record — one application on one laptop (Windows / macOS / Linux)", {
    x: MX + 0.22, y: cy + 0.56, w: cw - 0.44, h: 1.2, margin: 0, valign: "top",
    fontFace: BODY, fontSize: 11.5, color: INK,
  });
  s.addShape(pptx.ShapeType.line, {
    x: MX + cw + 0.18, y: cy + chh / 2, w: 0.65, h: 0,
    line: { color: TEAL, width: 2.5, endArrowType: "triangle" },
  });
  const c2x = MX + cw + 1.01;
  s.addText("ANALYSIS — ANY MACHINE", {
    x: c2x, y: cy - 0.42, w: cw, h: 0.3, margin: 0,
    fontFace: BODY, fontSize: 10, bold: true, color: TEAL, charSpacing: 1.5,
  });
  card(s, c2x, cy, cw, chh);
  s.addText("PRESTO v6.0.0 + TEMPO2", {
    x: c2x + 0.22, y: cy + 0.16, w: cw - 0.44, h: 0.34, margin: 0,
    fontFace: BODY, fontSize: 14.5, bold: true, color: NAVY,
  });
  s.addText(
    "the professional analysis suite, installed by one DSES build script — v6 barycenters in-process, so classic TEMPO is no longer needed",
    {
      x: c2x + 0.22, y: cy + 0.56, w: cw - 0.44, h: 1.2, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 11.5, color: INK,
    }
  );
  // subdued strip mirroring the PSRCHIVE row on the previous slide
  card(s, MX, 6.3, 2 * cw + 1.01, 0.62, "F7FAFB", "E5EDF1");
  s.addText(
    [
      { text: "That’s the whole list", options: { bold: true, color: MUTED } },
      {
        text: "  —  no Wine, no custom flowgraphs, no hand-edited configuration files",
        options: { color: "93A2AA" },
      },
    ],
    { x: MX + 0.22, y: 6.3, w: 2 * cw + 1.01 - 0.44, h: 0.62, margin: 0, valign: "middle", fontFace: BODY, fontSize: 11.5 }
  );
  // right stats, mirroring the previous slide
  stat(s, 9.6, 2.42, 3.1, "2", "pieces in the whole chain — acquisition and analysis", TEAL);
  stat(s, 9.6, 4.32, 3.1, "1", "build script installs the analysis stack, per platform", GOLD);
  s.addText("Same professional-quality results — on a far gentler learning curve.", {
    x: 9.6, y: 6.12, w: 3.1, h: 0.7, margin: 0, valign: "top",
    fontFace: BODY, fontSize: 11.5, italic: true, color: MUTED,
  });
  s.addNotes(
    "Deliberate contrast with the previous slide: the wall of chips collapses to two. On site, the Spectrum " +
      "Analyzer does everything the observer needs; at home (or in the field), PRESTO v6 plus TEMPO2 does the " +
      "analysis. PRESTO v6 dropped the classic-TEMPO dependency — barycentering is in-process and polycos come " +
      "from TEMPO2 — and both installations are captured as re-runnable build scripts in the Society's repository " +
      "(WSL on Windows, macOS)."
  );
}

// =================================================================================
// 4 — THE ANSWER
// =================================================================================
{
  const s = lightSlide("The instrument", "One instrument instead of a toolchain");
  s.addText(
    [
      { text: "The DSES Spectrum Analyzer", options: { bold: true, color: NAVY } },
      {
        text:
          " — a cross-platform application written within the Society. Born as an RFI-survey " +
          "instrument for the Haswell site, it has grown into a radio-astronomy data-acquisition system.",
        options: {},
      },
    ],
    { x: MX, y: 1.58, w: 8.1, h: 0.95, margin: 0, fontFace: BODY, fontSize: 14, color: INK }
  );
  const feats = [
    ["Plan", "live altitude/azimuth for catalog pulsars, computed from the site"],
    ["Survey", "real-time spectrum and waterfall; wide-band Sweep mode for RFI surveys"],
    ["Verify", "confirm the RF path is alive and clean before committing to a recording"],
    ["Record", "industry-standard SIGPROC .fil files — source name and RA/Dec stamped in the header"],
    ["Update", "built-in updater keeps observatory and member machines on the released baseline"],
  ];
  let fy = 2.72;
  feats.forEach(([name, desc], i) => {
    numDot(s, MX, fy, String(i + 1), TEAL);
    s.addText(
      [
        { text: name + "  —  ", options: { bold: true, color: NAVY } },
        { text: desc, options: { color: INK } },
      ],
      { x: MX + 0.62, y: fy - 0.05, w: 7.55, h: 0.55, margin: 0, valign: "middle", fontFace: BODY, fontSize: 13.5 }
    );
    fy += 0.82;
  });
  // right visual
  card(s, 9.35, 1.62, 3.35, 4.35, NAVY, NAVY);
  s.addImage({ path: APP_ICON, x: 10.325, y: 2.0, w: 1.4, h: 1.4, rounding: true });
  s.addText("DSES Spectrum Analyzer", {
    x: 9.55, y: 3.6, w: 2.95, h: 0.55, margin: 0, align: "center",
    fontFace: HEAD, fontSize: 15, bold: true, color: WHITE,
  });
  s.addText("drives the Ettus USRP B210\nand other SDRs", {
    x: 9.55, y: 4.18, w: 2.95, h: 0.6, margin: 0, align: "center",
    fontFace: BODY, fontSize: 11.5, color: ICE,
  });
  s.addText("v1.1.7 — released July 18, 2026", {
    x: 9.55, y: 5.42, w: 2.95, h: 0.3, margin: 0, align: "center",
    fontFace: BODY, fontSize: 10.5, color: GOLD_SOFT,
  });
  s.addText("Windows  •  macOS  •  Linux (incl. Raspberry Pi 5 field box)", {
    x: 9.35, y: 6.22, w: 3.35, h: 0.6, margin: 0, align: "center", valign: "top",
    fontFace: BODY, fontSize: 11, color: MUTED,
  });
  s.addNotes(
    "Everything the observer does on site — plan, survey, verify, record — in one package. " +
      "The analysis side (PRESTO) stays the professional standard; the acquisition side no longer requires it " +
      "to be assembled by hand. Distribution is from the Society's server with a built-in update checker."
  );
}

// =================================================================================
// 5 — THE EXPERIMENT
// =================================================================================
{
  const s = lightSlide("The experiment — July 11, 2026", "Put non-experts in front of the dish");
  card(s, MX, 1.62, 12.09, 1.5, TINT, TINT_LN);
  s.addText(
    [
      { text: "The question:  ", options: { bold: true, color: TEAL } },
      {
        text:
          "can members who are not pulsar-processing experts plan an observation, capture pulsar " +
          "data, and process it into professional-quality reports?",
        options: { color: NAVY },
      },
    ],
    {
      x: MX + 0.35, y: 1.62, w: 11.4, h: 1.5, margin: 0, valign: "middle",
      fontFace: HEAD, fontSize: 18, italic: true,
    }
  );
  const team = [
    ["RU", "Ray Uberecken", "AA0L"],
    ["AH", "Anne Haney", "W0ZDW"],
    ["RH", "Richard Hambly", "K0GD"],
  ];
  const tcw = 3.89, tcx0 = MX, tcy = 3.55;
  team.forEach(([ini, name, call], i) => {
    const x = tcx0 + i * (tcw + 0.21);
    card(s, x, tcy, tcw, 1.55);
    s.addText(ini, {
      shape: pptx.ShapeType.ellipse, x: x + 0.28, y: tcy + 0.4, w: 0.75, h: 0.75, margin: 0,
      fill: { color: TEAL }, line: { color: TEAL, width: 0 },
      align: "center", valign: "middle", fontFace: BODY, fontSize: 16, bold: true, color: WHITE,
    });
    s.addText(name, {
      x: x + 1.2, y: tcy + 0.38, w: tcw - 1.4, h: 0.4, margin: 0,
      fontFace: BODY, fontSize: 14.5, bold: true, color: NAVY,
    });
    s.addText(call, {
      x: x + 1.2, y: tcy + 0.78, w: tcw - 1.4, h: 0.35, margin: 0,
      fontFace: BODY, fontSize: 12.5, color: GOLD,
    });
  });
  const setup = [
    ["60-ft dish", "DSES site, Haswell, Colorado"],
    ["Ettus USRP B210", "software-defined radio receiver"],
    ["Spectrum Analyzer", "one laptop — planning, RF checks, recording"],
  ];
  setup.forEach(([big, small], i) => {
    const x = tcx0 + i * (tcw + 0.21);
    card(s, x, 5.4, tcw, 1.3, WHITE, TINT_LN);
    s.addText(big, {
      x: x + 0.25, y: 5.58, w: tcw - 0.5, h: 0.4, margin: 0,
      fontFace: HEAD, fontSize: 15.5, bold: true, color: TEAL,
    });
    s.addText(small, {
      x: x + 0.25, y: 5.98, w: tcw - 0.5, h: 0.55, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 11.5, color: INK,
    });
  });
  s.addNotes(
    "The Society's first live pulsar session using its own software. Team of three; none are " +
      "pulsar-processing experts in the sense of the previous slide. Everything on site ran through " +
      "the Spectrum Analyzer on one laptop driving the B210 at the 60-foot dish."
  );
}

// =================================================================================
// 6 — OBSERVATIONS
// =================================================================================
{
  const s = lightSlide("The data", "Two pulsars recorded live to filterbank");
  const geo = [
    ["20 MHz", "bandwidth, centered on 420 MHz"],
    ["256", "frequency channels"],
    ["204.8 µs", "time resolution"],
    ["32-bit", "samples — SIGPROC .fil"],
  ];
  const gw = 2.92, gy = 1.66;
  geo.forEach(([big, label], i) => {
    stat(s, MX + i * (gw + 0.14), gy, gw, big, label, i === 0 ? GOLD : TEAL);
  });
  const tableRows = [
    [
      { text: "Target", options: { bold: true, color: WHITE, fill: { color: TEAL } } },
      { text: "Start (MDT)", options: { bold: true, color: WHITE, fill: { color: TEAL } } },
      { text: "Duration", options: { bold: true, color: WHITE, fill: { color: TEAL } } },
      { text: "Data volume", options: { bold: true, color: WHITE, fill: { color: TEAL } } },
      { text: "Why this target", options: { bold: true, color: WHITE, fill: { color: TEAL } } },
    ],
    [
      { text: "B0329+54", options: { bold: true, color: NAVY } },
      { text: "14:17", options: {} },
      { text: "36.6 min", options: {} },
      { text: "11.0 GB", options: {} },
      { text: "Brightest northern pulsar — the standard reference source", options: {} },
    ],
    [
      { text: "B0950+08", options: { bold: true, color: NAVY } },
      { text: "15:12", options: {} },
      { text: "22.2 min", options: {} },
      { text: "6.7 GB", options: {} },
      { text: "Bright, low-dispersion; transiting at ~59° altitude during the session", options: {} },
    ],
  ];
  s.addTable(tableRows, {
    x: MX, y: 3.85, w: 12.09,
    colW: [1.85, 1.45, 1.45, 1.55, 5.79],
    rowH: [0.5, 0.72, 0.72],
    fontFace: BODY, fontSize: 12.5, color: INK, valign: "middle",
    border: { type: "solid", pt: 0.75, color: TINT_LN },
    fill: { color: WHITE },
    margin: [0.06, 0.1, 0.06, 0.1],
  });
  s.addText(
    "Targets were chosen live — the software computed current altitude/azimuth for the catalog pulsars from " +
      "the Haswell site. Most southern sources never rise there, which made the transiting B0950+08 the natural second pick.",
    { x: MX, y: 6.2, w: 12.0, h: 0.7, margin: 0, valign: "top", fontFace: BODY, fontSize: 12.5, italic: true, color: MUTED }
  );
  s.addNotes(
    "Same geometry for both recordings: 20 MHz at 420 MHz, 256 channels, 204.8 microsecond sampling, " +
      "32-bit — written directly as SIGPROC filterbank, the format PRESTO consumes. " +
      "Nearly 18 GB across the two targets."
  );
}

// =================================================================================
// 7 — B0329+54 RESULT
// =================================================================================
{
  const s = lightSlide("Results", "B0329+54 — a textbook detection");
  const fw = 6.62, fh = fw * (1087 / 1542);
  figFrame(s, FIG_0329R, 6.15, 1.78, fw, fh);
  s.addText("Gap-bridged, RFI-cleaned ephemeris fold — the full 36.6-minute integration (2026-07-17 re-analysis)", {
    x: 6.15, y: 6.55, w: fw, h: 0.3, margin: 0, align: "center",
    fontFace: BODY, fontSize: 10.5, italic: true, color: MUTED,
  });
  s.addText("28.0 σ", {
    x: MX, y: 1.85, w: 4.9, h: 1.0, margin: 0,
    fontFace: HEAD, fontSize: 60, bold: true, color: TEAL,
  });
  s.addText("probability the signal is noise: < 8×10⁻¹⁷³", {
    x: MX, y: 2.95, w: 4.9, h: 0.35, margin: 0,
    fontFace: BODY, fontSize: 13, color: GOLD, bold: true,
  });
  s.addText(
    [
      { text: "Textbook single-peaked profile at the catalog period of 714.5 ms, coherent across the full 36.6 minutes", options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
      { text: "Detection peaks at dispersion measure ≈ 25 — catalog value 26.8 — and falls off toward zero", options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
      { text: "In the field it stood at ~20 σ; RFI cleanup and one timebase repair recovered the rest — that story is the next slide", options: { bullet: true } },
    ],
    { x: MX, y: 3.55, w: 5.1, h: 3.1, margin: 0, valign: "top", fontFace: BODY, fontSize: 13.5, color: INK }
  );
  s.addNotes(
    "Walk the figure: single clean pulse top-left, single vertical track in phase-vs-time, DM curve peaking " +
      "near catalog. The number's history: ~19.9-20.6 sigma across the original fold types as reported in the " +
      "field; RFI mask + zap took it to 22.4; bridging a 0.558-second dropped-sample gap recovered full " +
      "coherence at 28.0 sigma with DM back at 25.3. Chi-squared_red 16.75."
  );
}

// =================================================================================
// 7b — PEER REVIEW / TIMEBASE FORENSICS
// =================================================================================
{
  const s = lightSlide("Peer review", "One review comment was worth 5.6 σ");
  const steps = [
    ["The comment", "Dan Layne (AD0CY), reviewing the trip report: the fold shows a phase drift it shouldn’t have"],
    ["The forensics", "A rigid no-search ephemeris fold: smooth 1.2-rotation drift plus one +0.22-rotation step — parts in 10⁴, five orders beyond any physics. Our clock, not the sky"],
    ["The culprit", "USB sample drops during recording silently shorten the .fil’s sample-count clock — the app showed overflows live but didn’t count or log them"],
    ["The repair", "0.558 s of noise padded at the step: 22.4 σ → 28.0 σ, single textbook profile, DM back at 25.3 — diagnosis confirmed by repair"],
  ];
  const scw = 2.92, sy = 2.0, sh = 3.3;
  steps.forEach(([name, desc], i) => {
    const x = MX + i * (scw + 0.14);
    card(s, x, sy, scw, sh);
    numDot(s, x + 0.24, sy + 0.28, String(i + 1), i === 3 ? GOLD : TEAL, 0.52);
    s.addText(name, {
      x: x + 0.24, y: sy + 1.0, w: scw - 0.48, h: 0.4, margin: 0,
      fontFace: HEAD, fontSize: 15, bold: true, color: NAVY,
    });
    s.addText(desc, {
      x: x + 0.24, y: sy + 1.45, w: scw - 0.48, h: sh - 1.6, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 11.5, color: INK,
    });
  });
  card(s, MX, 5.75, 12.09, 1.0, TINT, TINT_LN);
  s.addText(
    [
      { text: "Return on criticism.  ", options: { bold: true, color: GOLD } },
      {
        text: "Overflow logging and automatic gap-padding are now queued on the roadmap — future recordings keep an honest clock.",
        options: { color: NAVY },
      },
    ],
    { x: MX + 0.35, y: 5.75, w: 11.4, h: 1.0, margin: 0, valign: "middle", fontFace: BODY, fontSize: 14.5 }
  );
  s.addNotes(
    "The drift function was mapped directly: 22 consecutive 100-second fixed-period folds, each window's " +
      "phase measured by cross-correlation — a smooth accelerating drip plus one discrete +0.219-rotation step " +
      "at t ≈ 550 s. The pad is 0.025% of the data, a copy of the preceding real noise — no synthetic signal; " +
      "it only restores the time axis. The 5.6-sigma jump is the coherence recovered when the two segments " +
      "finally add in phase. Caveat: the padded file is for detection and profile work, not absolute timing. " +
      "Full analysis in the refined fold PDFs beside the recordings."
  );
}

// =================================================================================
// 8 — B0950+08 RESULT
// =================================================================================
{
  const s = lightSlide("Results", "B0950+08 — a strong candidate, honestly framed");
  const fw = 6.62, fh = fw * (1157 / 1637);
  figFrame(s, FIG_0950, 6.15, 1.78, fw, fh);
  s.addText("Fold at the known 253 ms period — 22.2-minute observation", {
    x: 6.15, y: 6.55, w: fw, h: 0.3, margin: 0, align: "center",
    fontFace: BODY, fontSize: 10.5, italic: true, color: MUTED,
  });
  s.addText("~9 σ", {
    x: MX, y: 1.85, w: 4.9, h: 1.0, margin: 0,
    fontFace: HEAD, fontSize: 60, bold: true, color: TEAL,
  });
  s.addText("after cleanup, the best fit lands on the catalog values", {
    x: MX, y: 2.95, w: 4.9, h: 0.35, margin: 0,
    fontFace: BODY, fontSize: 13, color: GOLD, bold: true,
  });
  s.addText(
    [
      { text: "Clear peak at the pulsar’s 253 ms period when folded at the known ephemeris (~9.7 σ as recorded)", options: { bullet: true, breakLine: true, paraSpaceAfter: 9 } },
      { text: "With RFI masked and the timebase repaired, the search converges on P = 253.05 ms and DM ≈ 2.9 — the catalog values — exactly how a real detection behaves", options: { bullet: true, breakLine: true, paraSpaceAfter: 9 } },
      { text: "But it is noise-limited: at 20 MHz bandwidth DM 2.97 is indistinguishable from zero, and ~9 σ leaves no room for decisive sub-tests — a strong candidate, not yet a publishable detection", options: { bullet: true, breakLine: true, paraSpaceAfter: 9 } },
      { text: "The remaining gains are observational: a 90-minute track (≈20 σ), several sessions to catch scintillation maxima, wider bandwidth", options: { bullet: true } },
    ],
    { x: MX, y: 3.55, w: 5.1, h: 3.2, margin: 0, valign: "top", fontFace: BODY, fontSize: 12.5, color: INK }
  );
  s.addNotes(
    "Honesty is the credibility of the whole talk: the 2026-07-17 re-analysis applied the full B0329+54 " +
      "cleanup — the significance stays ~9 sigma (noise-limited, not artifact-limited), but the best-fit " +
      "parameters walk onto the catalog values for the first time. A predictive split-half coherence test " +
      "came out consistent (~2 sigma) but not decisive — at 9 sigma total, subdividing runs out of signal. " +
      "Processing gains are exhausted; the re-observation plan is on the roadmap: record after the timebase " +
      "fix ships, 90+ minutes, multiple sessions for scintillation."
  );
}

// =================================================================================
// 9 — VERIFICATION
// =================================================================================
{
  const s = lightSlide("Verification", "Real — and independently reproducible");
  // left card: dispersion
  card(s, MX, 1.7, 5.9, 4.35);
  s.addText("Dispersion: the celestial fingerprint", {
    x: MX + 0.3, y: 1.95, w: 5.3, h: 0.4, margin: 0,
    fontFace: HEAD, fontSize: 17, bold: true, color: NAVY,
  });
  s.addText(
    [
      { text: "Interstellar plasma delays lower frequencies — a sweep imposed by light-years of travel", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: "Detection strength peaks at the catalog dispersion measure and falls toward zero", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: "Terrestrial interference shows no dispersion at all", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: "One curve separates a genuine pulsar from RFI", options: { bullet: true, bold: true, color: TEAL } },
    ],
    { x: MX + 0.3, y: 2.5, w: 5.3, h: 3.3, margin: 0, valign: "top", fontFace: BODY, fontSize: 13, color: INK }
  );
  // right card: cross-platform
  const rx = 6.8;
  card(s, rx, 1.7, 5.9, 4.35);
  s.addText("Two platforms, two toolchains, one answer", {
    x: rx + 0.3, y: 1.95, w: 5.3, h: 0.4, margin: 0,
    fontFace: HEAD, fontSize: 17, bold: true, color: NAVY,
  });
  s.addText(
    [
      { text: "macOS — PRESTO v5.0.2, re-run on v6.0.0", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: "Windows — PRESTO v6.0.0 under WSL (a new DSES capability)", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
      { text: "Identical fold commands, independently built stacks", options: { bullet: true } },
    ],
    { x: rx + 0.3, y: 2.5, w: 5.3, h: 1.6, margin: 0, valign: "top", fontFace: BODY, fontSize: 13, color: INK }
  );
  card(s, rx + 0.3, 4.35, 5.3, 1.35, WHITE, TINT_LN);
  s.addText(
    [
      { text: "B0329+54 probability-of-noise\n", options: { fontSize: 11, color: MUTED } },
      { text: "4.49×10⁻⁹⁰", options: { fontSize: 19, bold: true, color: TEAL } },
      { text: "  Windows      ", options: { fontSize: 11, color: INK } },
      { text: "4.5×10⁻⁹⁰", options: { fontSize: 19, bold: true, color: GOLD } },
      { text: "  macOS", options: { fontSize: 11, color: INK } },
    ],
    { x: rx + 0.55, y: 4.45, w: 4.9, h: 1.15, margin: 0, valign: "middle", fontFace: BODY }
  );
  s.addText(
    "Every fold now produces a standardized PDF diagnostic stored beside the recording — validation minutes after capture, on whichever machine is at hand.",
    { x: MX, y: 6.35, w: 12.0, h: 0.6, margin: 0, valign: "top", fontFace: BODY, fontSize: 12.5, italic: true, color: MUTED }
  );
  s.addNotes(
    "Two independent arguments. Physics: the dispersion curve is the fingerprint — RFI doesn't have one. " +
      "Engineering: the same recordings re-analyzed on separately compiled PRESTO builds on two operating " +
      "systems agree to three significant figures."
  );
}

// =================================================================================
// 10 — FIELD ENGINEERING
// =================================================================================
{
  const s = lightSlide("Field engineering", "The case of the headless Raspberry Pi");
  const steps = [
    ["Symptoms", "Dropdown menus dead, Help menu blank, window opens tiny in a corner — on the field box, mid-session"],
    ["Diagnosis", "Remote SSH into the site over Tailscale — while the trip continued"],
    ["Root cause", "No monitor attached: the graphics system reports a 0×0-pixel screen, collapsing every popup and confusing window placement"],
    ["Fix — in v1.1.6", "Launcher synthesizes a virtual monitor when none is connected; the app refuses to reposition windows against an empty screen"],
  ];
  const scw = 2.92, sy = 2.0, sh = 3.1;
  steps.forEach(([name, desc], i) => {
    const x = MX + i * (scw + 0.14);
    card(s, x, sy, scw, sh);
    numDot(s, x + 0.24, sy + 0.28, String(i + 1), i === 3 ? GOLD : TEAL, 0.52);
    s.addText(name, {
      x: x + 0.24, y: sy + 1.0, w: scw - 0.48, h: 0.4, margin: 0,
      fontFace: HEAD, fontSize: 15, bold: true, color: NAVY,
    });
    s.addText(desc, {
      x: x + 0.24, y: sy + 1.45, w: scw - 0.48, h: sh - 1.6, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 11.5, color: INK,
    });
  });
  card(s, MX, 5.55, 12.09, 1.1, TINT, TINT_LN);
  s.addText(
    [
      { text: "Not an application bug.  ", options: { bold: true, color: GOLD } },
      {
        text: "A display-configuration condition that had silently affected every prior software version — found because real hardware was running at a real site.",
        options: { color: NAVY },
      },
    ],
    { x: MX + 0.35, y: 5.55, w: 11.4, h: 1.1, margin: 0, valign: "middle", fontFace: BODY, fontSize: 14.5 }
  );
  s.addNotes(
    "Crowd-pleaser story: the field box (Raspberry Pi 5, viewed over remote desktop) had 'broken' menus. " +
      "Every symptom traced to one condition — headless operation yields a zero-by-zero screen. " +
      "The fix shipped in v1.1.6 and the box was verified running it. Moral for any club running remote gear."
  );
}

// =================================================================================
// 11 — v1.1.6
// =================================================================================
{
  const s = lightSlide("Shipped", "Field wish-list → v1.1.6 in two days");
  s.addText("Spectrum Analyzer v1.1.6 — cut and published July 12, one day after the observing session:", {
    x: MX, y: 1.58, w: 11.5, h: 0.4, margin: 0, fontFace: BODY, fontSize: 14, color: INK,
  });
  const cards = [
    ["Sweep mode", "Stepped wide-spectrum scan for RFI surveys beyond the radio’s instantaneous bandwidth — retunes across a range (e.g. 100–1000 MHz) and stitches one wide trace, with cross-pass max-hold."],
    ["Recording, finished", "Source name stamped into the filename and the .fil header — with RA/Dec derived from the pulsar designation. Red REC indicator, elapsed time, timed auto-stop. July 11’s files had to be renamed and patched by hand; never again."],
    ["Headless fixes", "The virtual-monitor launcher and empty-screen safeguards from the previous slide, plus updated documentation and operating guide."],
  ];
  const ccw = 3.89, cy = 2.2, ch = 2.9;
  cards.forEach(([name, desc], i) => {
    const x = MX + i * (ccw + 0.21);
    card(s, x, cy, ccw, ch);
    s.addText(name, {
      x: x + 0.26, y: cy + 0.22, w: ccw - 0.52, h: 0.42, margin: 0,
      fontFace: HEAD, fontSize: 16.5, bold: true, color: TEAL,
    });
    s.addText(desc, {
      x: x + 0.26, y: cy + 0.72, w: ccw - 0.52, h: ch - 0.95, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 12, color: INK,
    });
  });
  card(s, MX, 5.4, 12.09, 1.35, WHITE, TINT_LN);
  s.addText(
    [
      { text: "Epilogue: ", options: { bold: true, color: GOLD } },
      {
        text:
          "one day after release, the field box caught a packaging defect desktop testing had missed — Windows line endings " +
          "in the Unix launcher script. Rebuilt and republished within hours, with two independent build-pipeline safeguards added. " +
          "Real installations in the field earn their keep.",
        options: { color: INK },
      },
    ],
    { x: MX + 0.3, y: 5.4, w: 11.5, h: 1.35, margin: 0, valign: "middle", fontFace: BODY, fontSize: 12.5 }
  );
  s.addNotes(
    "Everything the field session asked for shipped within two days, and every machine — including the field " +
      "box — converged on the release through the built-in updater. The line-endings epilogue is worth telling: " +
      "the first Windows-built archive broke Unix launches; the field box exposed it within a day."
  );
}

// =================================================================================
// 11b — v1.1.7
// =================================================================================
{
  const s = lightSlide("Shipped, again", "v1.1.7 six days later — the display was hiding signals");
  const steps = [
    ["The report", "Ray (AA0L): on the same hardware, other SDR software shows weak signals ours doesn’t"],
    ["The root cause", "The display FFT examined only the newest FFT-length of samples each screen tick — about 0.3% of the stream at 20 MS/s. The other 99.7% never reached the screen"],
    ["The fix", "Welch-average every sample between screen updates; true per-block peak/min hold detectors; an adaptive CPU budget so slower machines shed coverage gracefully"],
    ["The result", "A razor-flat noise floor with sub-dB scatter — weak signals stand clear. Verified live on the B210; released July 18"],
  ];
  const scw = 2.92, sy = 2.0, sh = 3.3;
  steps.forEach(([name, desc], i) => {
    const x = MX + i * (scw + 0.14);
    card(s, x, sy, scw, sh);
    numDot(s, x + 0.24, sy + 0.28, String(i + 1), i === 3 ? GOLD : TEAL, 0.52);
    s.addText(name, {
      x: x + 0.24, y: sy + 1.0, w: scw - 0.48, h: 0.4, margin: 0,
      fontFace: HEAD, fontSize: 15, bold: true, color: NAVY,
    });
    s.addText(desc, {
      x: x + 0.24, y: sy + 1.45, w: scw - 0.48, h: sh - 1.6, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 11.5, color: INK,
    });
  });
  card(s, MX, 5.75, 12.09, 1.0, TINT, TINT_LN);
  s.addText(
    [
      { text: "Recordings were never affected", options: { bold: true, color: GOLD } },
      {
        text:
          " — the filterbank path always processed every sample; this was display-only. Two field reports, two releases, seven days.",
        options: { color: NAVY },
      },
    ],
    { x: MX + 0.35, y: 5.75, w: 11.4, h: 1.0, margin: 0, valign: "middle", fontFace: BODY, fontSize: 14.5 }
  );
  s.addNotes(
    "The noise-floor scatter dropped ~34x (≈ sqrt of the averaging depth); max hold is now a true per-block " +
      "peak detector, so a 51-microsecond burst reads at full amplitude instead of -27 dB. One release note " +
      "worth mentioning: the default average is now linear power, so the displayed floor reads about +2.5 dB " +
      "versus older versions — the old dB-domain average was biased low; the new number is the honest one. " +
      "Verified live on the B210 at 1422 MHz with three weak narrowband test signals."
  );
}

// =================================================================================
// 12 — NEXT STEPS
// =================================================================================
{
  const s = lightSlide("The road ahead", "A documented upgrade queue");
  const queue = [
    ["Pulsar visibility planner", "“what’s up now?” — pulsars above the horizon with az/el, flux, and time left; a pick fills the recording Source field"],
    ["One-click post-processing", "“is it good?” — automatic RFI mask + catalog fold when a recording ends; sigma/DM results card and a plain verdict"],
    ["Quick-look during recording", "a draft fold on a snapshot of the data so far — without interrupting a multi-hour capture"],
    ["Timebase integrity", "count and log overflows; automatic gap-padding keeps the .fil clock honest — the peer-review finding, fixed at the source"],
    ["Self-contained fold PDFs", "commands, results table, and plain-language verdict inside every chart PDF — nothing to chase down later"],
    ["Audio demodulators for RFI ID", "click a signal and listen — AM/NFM/WFM/SSB/CW; an AI mode-classifier to follow"],
    ["System-1 steering integration", "pick a pulsar in the app and the dish knows where to point — awaiting the steering team’s API"],
    ["ezRA drift-scan format", "record ezCol-compatible files for the open-source hydrogen-line drift-scan suite"],
  ];
  const qw = 4.25, qh = 1.05, qgx = 0.22, qgy = 0.14, qy0 = 1.95;
  queue.forEach(([name, desc], i) => {
    const x = MX + (i % 2) * (qw + qgx);
    const y = qy0 + Math.floor(i / 2) * (qh + qgy);
    card(s, x, y, qw, qh);
    s.addText(name, {
      x: x + 0.2, y: y + 0.09, w: qw - 0.4, h: 0.28, margin: 0,
      fontFace: BODY, fontSize: 11.5, bold: true, color: NAVY,
    });
    s.addText(desc, {
      x: x + 0.2, y: y + 0.38, w: qw - 0.4, h: 0.62, margin: 0, valign: "top",
      fontFace: BODY, fontSize: 9.5, color: INK,
    });
  });
  stat(s, 9.6, 1.95, 3.1, "8", "features specified and committed to the Society’s shared roadmap", TEAL);
  stat(s, 9.6, 3.85, 3.1, "≈20 σ", "expected from a 90-minute B0950+08 re-observation once the timebase fix ships", GOLD);
  s.addText(
    "Plus a site-computer upgrade to multi-core x86-64 — enabling PRESTO post-processing right at the dish.",
    { x: 9.6, y: 5.65, w: 3.1, h: 1.1, margin: 0, valign: "top", fontFace: BODY, fontSize: 11.5, italic: true, color: MUTED }
  );
  s.addText(
    "Training the radio-astronomy interest group starts on this baseline — a roster of members is signed up.",
    { x: MX, y: 6.85, w: 8.72, h: 0.35, margin: 0, valign: "top", fontFace: BODY, fontSize: 11.5, italic: true, color: MUTED }
  );
  s.addNotes(
    "This is not a wish list — every item is specified in the repository's shared ROADMAP.md with design " +
      "notes. The queue turns the remaining expertise into software: the planner replaces the Murmur/Stellarium " +
      "planning step, one-click post-processing replaces the hand-run PRESTO pipeline for the common case, and " +
      "timebase integrity fixes the defect peer review found. Science queue alongside: the B0950+08 campaign, " +
      "and repeated B0329+54 sessions toward timing-grade data."
  );
}

// =================================================================================
// 13 — TAKEAWAYS (dark)
// =================================================================================
{
  const s = pptx.addSlide();
  s.background = { color: NAVY };
  pageNo++;
  darkRings(s, 12.6, 6.9);
  s.addText("WHAT WE PROVED AT HASWELL", {
    x: 0.75, y: 0.6, w: 9.0, h: 0.35, margin: 0,
    fontFace: BODY, fontSize: 12.5, bold: true, color: GOLD_SOFT, charSpacing: 2,
  });
  const takes = [
    "Non-experts detected B0329+54 at 28 σ — plus a strong second candidate — with software the Society wrote, controls, and can teach.",
    "The whole data path — antenna → SDR → filterbank → PRESTO — is validated end to end, reproduced across platforms, and hardened by peer review.",
    "The barrier is now a slope: two releases shipped from field feedback in a week, and the upgrade queue is written down.",
  ];
  let ty = 1.35;
  takes.forEach((t, i) => {
    numDot(s, 0.78, ty + 0.06, String(i + 1), GOLD, 0.5);
    s.addText(t, {
      x: 1.55, y: ty - 0.12, w: 10.6, h: 1.0, margin: 0, valign: "middle",
      fontFace: HEAD, fontSize: 19, bold: true, color: WHITE,
    });
    ty += 1.18;
  });
  s.addShape(pptx.ShapeType.line, {
    x: 0.78, y: 5.05, w: 10.5, h: 0, line: { color: RING, width: 1 },
  });
  s.addText(
    [
      { text: "Standing on the work of Dr. Richard Russel (AC0UB) and Dan Layne (AD0CY) — whose review of the report made the headline number stronger.\n", options: {} },
      { text: "Field team: Ray Uberecken (AA0L), Anne Haney (W0ZDW), Richard Hambly (K0GD).\n", options: {} },
      { text: "Development, field diagnosis, and data processing accelerated by AI-assisted engineering (Claude Code).", options: {} },
    ],
    { x: 0.78, y: 5.25, w: 10.8, h: 1.05, margin: 0, valign: "top", fontFace: BODY, fontSize: 12.5, color: ICE, lineSpacingMultiple: 1.25 }
  );
  s.addText(
    [
      { text: "Richard M. Hambly (K0GD)", options: { bold: true, color: WHITE } },
      { text: "   •   rick@cnssys.com   •   dses.science", options: { color: GOLD_SOFT } },
    ],
    { x: 0.78, y: 6.5, w: 9.0, h: 0.4, margin: 0, fontFace: BODY, fontSize: 14 }
  );
  s.addImage({ path: LOGO_REV, x: 10.35, y: 6.28, w: 2.3, h: 0.944 });
  s.addNotes(
    "Close on the mission, not the software: this was about opening real radio astronomy to more members. " +
      "Thanks: Rich and Dan built the program this stands on; the field team; and the report notes the role of " +
      "AI-assisted engineering across three platforms. Questions."
  );
}

// ---------------------------------------------------------------------------------
const OUT = path.join(__dirname, "Lowering_the_Barrier_to_Radio_Astronomy_SARA_2026.pptx");

// Clobber guard (same policy as build_doc.py): if the .pptx differs from the
// committed version, it may carry hand edits made in PowerPoint — refuse to
// overwrite unless invoked with --force.
if (!process.argv.includes("--force")) {
  try {
    const st = require("child_process")
      .execSync(`git status --porcelain -- "${path.basename(OUT)}"`, { cwd: __dirname })
      .toString()
      .trim();
    if (/^.?M/.test(st)) {
      console.error(
        "REFUSING to overwrite: the .pptx has uncommitted changes (possibly hand edits\n" +
          "made in PowerPoint). Commit or port them first, or re-run with --force."
      );
      process.exit(1);
    }
  } catch (e) {
    /* not a git checkout — proceed */
  }
}

pptx.writeFile({ fileName: OUT }).then(() => console.log("wrote " + OUT));
