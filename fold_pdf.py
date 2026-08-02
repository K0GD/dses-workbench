#!/usr/bin/env python3
"""
fold_pdf.py -- self-contained fold-result PDFs (DSES convention).

Every prepfold result delivered as a PDF carries its interpretation WITH it:
chart page(s) first, then a commentary section (recording metadata, the exact
PRESTO commands run, a results table, and a plain-language verdict with
caveats), so nobody has to hunt for the analysis text elsewhere. See
CLAUDE.md "Fold-PDF convention".

Commentary lines use a tiny markup: lines starting with "## " are teal
section headings, lines starting with "|" render monospace (tables and
commands), everything else is wrapped body text.

Uses matplotlib (Agg) + PIL only — both ship in the app environment.
"""
import textwrap

import matplotlib
matplotlib.use("Agg")
# Embed TrueType (type 42) fonts, NOT matplotlib's default Type 3. Type 3
# stores each glyph as a PDF XObject procedure, and Adobe Acrobat crashes on
# these (observed 2026-08-02: "unhandled win32 exception in Acrobat.exe" when
# opening a fold PDF that rendered fine everywhere else — the em-dash glyphs
# were the Type 3 XObjects). Type 42 is also selectable/searchable text.
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image

PAGE = (11.0, 8.5)   # US letter landscape, matches prepfold plots
_TEAL = "#156082"    # DSES house heading color


def _chart_page(pdf, png_path, caption):
    fig = plt.figure(figsize=PAGE)
    img = Image.open(png_path)
    ax = fig.add_axes([0.02, 0.01, 0.96, 0.93])
    ax.imshow(img)
    ax.axis("off")
    fig.text(0.5, 0.97, caption, ha="center", va="top", fontsize=11,
             fontweight="bold")
    pdf.savefig(fig)
    plt.close(fig)


def _text_pages(pdf, lines, title):
    fig = plt.figure(figsize=PAGE)
    fig.text(0.5, 0.955, title, ha="center", va="top", fontsize=12,
             fontweight="bold")
    y = 0.905
    for kind, text in lines:
        if y < 0.05:
            pdf.savefig(fig)
            plt.close(fig)
            fig = plt.figure(figsize=PAGE)
            y = 0.94
        if kind == "head":
            y -= 0.015
            fig.text(0.05, y, text, fontsize=11, fontweight="bold",
                     va="top", color=_TEAL)
            y -= 0.032
        elif kind == "mono":
            fig.text(0.06, y, text, fontsize=8.2, family="monospace",
                     va="top")
            y -= 0.0245
        elif kind == "blank":
            y -= 0.012
        else:
            fig.text(0.05, y, text, fontsize=9.5, va="top")
            y -= 0.0245
    pdf.savefig(fig)
    plt.close(fig)


def parse_commentary(text):
    """Commentary string -> [(kind, line), ...] for _text_pages."""
    out = []
    for raw in text.splitlines():
        if raw.startswith("## "):
            out.append(("head", raw[3:]))
        elif raw.startswith("|"):
            out.append(("mono", raw[1:]))
        elif not raw.strip():
            out.append(("blank", ""))
        else:
            for w in textwrap.wrap(raw, 118) or [""]:
                out.append(("body", w))
    return out


def build_pdf(out_path, title, commentary_text, charts):
    """Write the PDF: `charts` is a list of (png_path, caption) pages, then
    the commentary (may span pages). Returns out_path."""
    with PdfPages(out_path) as pdf:
        for png, caption in charts:
            _chart_page(pdf, png, caption)
        _text_pages(pdf, parse_commentary(commentary_text), title)
        d = pdf.infodict()
        d["Title"] = title
        d["Author"] = "DSES / Rick Hambly K0GD"
    return out_path
