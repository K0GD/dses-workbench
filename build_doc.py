"""Build a DSES-styled PDF from a Markdown source (e.g. Installing.md).

The deliverable is the PDF:
    DSES_RFI_Spectrum_Analyzer_Installation.pdf

Internally the document is rendered to a temporary .docx (python-docx, styled
to match the DSES house template — margins, title color, Heading 1
white-on-teal banner, Heading 3 dark-teal, page header with "DSES" + subtitle,
footer with date + page number) and then converted to PDF. The .docx is a
throwaway intermediate — it is written to a temp file and removed after the
PDF is built, unless you pass --docx to keep it. PDF conversion uses
LibreOffice on macOS/Linux and Microsoft Word on Windows (see
convert_docx_to_pdf).

Handles the Markdown subset used in Installing.md:
    # / ## / ###       — headings
    paragraphs         — regular text with inline **bold**, *italic*, `code`
    - / *              — bulleted lists
    1.                 — numbered lists
    ```                — fenced code blocks (monospace, light-gray background)
    | a | b |          — tables (with --- alignment separator)
    [text](url)        — hyperlinks (rendered as text with the URL after, since
                         full hyperlink XML in python-docx is verbose)

Run from the project root with the project's conda env:
    .conda\\python.exe build_install_docx.py
"""

from __future__ import annotations

import html
import re
import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ---------------------------------------------------------------------------
# Smart-quote pre-pass: convert ASCII apostrophes and double quotes in body
# text to typographer equivalents, leaving fenced code blocks and inline
# `code` spans untouched. Matches DSES house style (Word's AutoCorrect would
# do the same thing for hand-typed text, but python-docx writes text
# verbatim and Word's autocorrect doesn't run on programmatic content).
# ---------------------------------------------------------------------------

LEFT_DOUBLE  = '“'   # "
RIGHT_DOUBLE = '”'   # "
APOSTROPHE   = '’'   # ’ (also doubles as right single quote)


def smartify_quotes(text: str) -> str:
    out = []
    in_fence = False
    dq_state = {'open': True}  # next " is opening
    for line in text.split('\n'):
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        # Reset double-quote state on paragraph breaks so an unmatched quote
        # in one paragraph doesn't flip the polarity for the next.
        if line.strip() == '':
            dq_state['open'] = True
        out.append(_smartify_line(line, dq_state))
    return '\n'.join(out)


def _smartify_line(line: str, dq_state: dict) -> str:
    result = []
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == '`':
            # Inline code span — emit verbatim through the closing backtick.
            j = line.find('`', i + 1)
            if j == -1:
                result.append(c)
                i += 1
                continue
            result.append(line[i:j + 1])
            i = j + 1
            continue
        if c == "'":
            # Apostrophe only if it's after a letter (contraction / possessive).
            # Leave others straight — they might be opening single quotes,
            # feet markers, or other punctuation.
            prev = line[i - 1] if i > 0 else ''
            if prev.isalpha():
                result.append(APOSTROPHE)
            else:
                result.append(c)
            i += 1
            continue
        if c == '"':
            result.append(LEFT_DOUBLE if dq_state['open'] else RIGHT_DOUBLE)
            dq_state['open'] = not dq_state['open']
            i += 1
            continue
        result.append(c)
        i += 1
    return ''.join(result)


# Defaults for the install guide; CLI options can override. Used as module-
# level constants because the cover-page / header builders read them.
SRC = Path("Installing.md")
DST_PDF  = Path("DSES_RFI_Spectrum_Analyzer_Installation.pdf")
DOC_TITLE    = "DSES Spectrum Analyzer"
DOC_SUBTITLE = "Installation Guide"
DOC_VERSION  = "v1.1.6"
DOC_AUTHOR   = "Richard M Hambly (K0GD)"
DOC_ORG      = "DSES"

# DSES house style (pulled from EVE-26 + Pulsar installation reference docs)
TITLE_COLOR_RGB     = RGBColor(0x15, 0x60, 0x82)  # teal/blue
H1_BG_HEX           = "156082"                    # same teal as banner fill
H1_TEXT_RGB         = RGBColor(0xFF, 0xFF, 0xFF)  # white on the banner
H3_COLOR_RGB        = RGBColor(0x0A, 0x2F, 0x40)  # dark teal
SUBTITLE_COLOR_RGB  = RGBColor(0x59, 0x59, 0x59)  # mid-gray
CODE_FILL_HEX       = "F2F2F2"                    # very light gray
PAGE_MARGINS = dict(  # inches; matches both DSES reference documents
    left=1.00, right=0.81, top=1.36, bottom=1.00,
)
# Optional logo shown right-justified in the page header (pages 2+). Set via
# --header-logo; None keeps the classic text-only header.
HEADER_LOGO = None


# ---------------------------------------------------------------------------
# Inline run handling — split "...some **bold** and `code` text..." into a
# list of (text, style_dict) tuples.
# ---------------------------------------------------------------------------

INLINE_RE = re.compile(
    r'(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|\[[^\]]+\]\([^)]+\))'
)
LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')


def parse_inline(text: str):
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            yield text[pos:m.start()], {}
        token = m.group(0)
        if token.startswith('**'):
            yield token[2:-2], {'bold': True}
        elif token.startswith('`'):
            yield token[1:-1], {'code': True}
        elif token.startswith('['):
            lm = LINK_RE.match(token)
            if lm:
                label, url = lm.group(1), lm.group(2)
                if label.strip() == url.strip():
                    yield label, {'code': True}
                else:
                    yield label, {}
                    yield f" ({url})", {'code': True}
        elif token.startswith('*'):
            yield token[1:-1], {'italic': True}
        pos = m.end()
    if pos < len(text):
        yield text[pos:], {}


def add_runs(paragraph, text: str):
    for chunk, style in parse_inline(text):
        if not chunk:
            continue
        chunk = html.unescape(chunk)
        run = paragraph.add_run(chunk)
        if style.get('bold'):
            run.bold = True
        if style.get('italic'):
            run.italic = True
        if style.get('code'):
            run.font.name = 'Consolas'
            run.font.size = Pt(10)


# ---------------------------------------------------------------------------
# DSES style primitives — small wrappers around the raw OOXML so the body
# of the document builder stays readable.
# ---------------------------------------------------------------------------

def set_cell_shading(cell, color_hex):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), color_hex)
    shd.set(qn('w:val'), 'clear')
    tc_pr.append(shd)


def set_paragraph_shading(paragraph, color_hex):
    """Paint a solid fill behind a paragraph (used for the DSES H1 banner)."""
    pPr = paragraph._element.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), color_hex)
    pPr.append(shd)


def add_page_number_field(paragraph):
    """Insert a PAGE field code so Word numbers pages live."""
    run = paragraph.add_run()
    for tag in ('begin', None, 'end'):
        if tag is None:
            instr = OxmlElement('w:instrText')
            instr.text = 'PAGE'
            run._r.append(instr)
        else:
            ch = OxmlElement('w:fldChar')
            ch.set(qn('w:fldCharType'), tag)
            run._r.append(ch)


def add_page_break(doc):
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)


# ---------------------------------------------------------------------------
# Cover page + section header/footer (DSES house style)
# ---------------------------------------------------------------------------

def configure_section(section):
    section.left_margin   = Inches(PAGE_MARGINS['left'])
    section.right_margin  = Inches(PAGE_MARGINS['right'])
    section.top_margin    = Inches(PAGE_MARGINS['top'])
    section.bottom_margin = Inches(PAGE_MARGINS['bottom'])

    # Suppress the header/footer on the cover page: enable a distinct
    # first-page header/footer and leave it empty. The primary header/footer
    # configured below then applies only to page 2 onward.
    section.different_first_page_header_footer = True

    # Header (pages 2+): document title on line 1, subtitle on line 2.
    hdr = section.header
    # Reuse existing first paragraph; we control its content fully.
    p1 = hdr.paragraphs[0]
    p1.text = ''
    r = p1.add_run(DOC_TITLE)
    r.bold = True
    r.font.size = Pt(11)
    r.font.color.rgb = TITLE_COLOR_RGB
    # Optional logo, right-justified on the title line via a right tab stop
    # at the text-column edge.
    if HEADER_LOGO and Path(HEADER_LOGO).is_file():
        content_w = 8.5 - PAGE_MARGINS['left'] - PAGE_MARGINS['right']
        p1.paragraph_format.tab_stops.add_tab_stop(
            Inches(content_w), WD_TAB_ALIGNMENT.RIGHT)
        # The built-in Header style carries center (3.25") and right (6.5")
        # stops; a single tab would land on the center one and park the logo
        # mid-page. Emit w:val="clear" entries so only our stop remains.
        # NOTE: w:tab elements must be in ascending w:pos order or Word
        # discards the list — insert 9360 first, then 4680 in front of it.
        tabs_el = p1._p.pPr.find(qn('w:tabs'))
        for pos_twips in ('9360', '4680'):          # 6.5" then 3.25"
            clear = OxmlElement('w:tab')
            clear.set(qn('w:val'), 'clear')
            clear.set(qn('w:pos'), pos_twips)
            tabs_el.insert(0, clear)
        p1.add_run('\t')
        p1.add_run().add_picture(str(HEADER_LOGO), height=Inches(0.42))
    p2 = hdr.add_paragraph()
    r2 = p2.add_run(DOC_SUBTITLE)
    r2.italic = True
    r2.font.size = Pt(9)
    r2.font.color.rgb = SUBTITLE_COLOR_RGB

    # Footer: date <tab> page number — matches the reference DSES docs.
    fp = section.footer.paragraphs[0]
    fp.text = ''
    today = date.today().strftime("%d-%b-%y")  # e.g. "16-May-26"
    fr = fp.add_run(today)
    fr.font.size = Pt(9)
    fr.font.color.rgb = SUBTITLE_COLOR_RGB
    fp.add_run('\t')
    add_page_number_field(fp)
    for run in fp.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = SUBTITLE_COLOR_RGB


def _toc_plain(title):
    """Strip the small subset of inline markdown the headings use, for a clean
    table-of-contents entry."""
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', title)   # [text](url) -> text
    return t.replace('**', '').replace('`', '').strip()


def collect_headings(lines):
    """(level, title) for every ATX heading in the markdown, skipping fenced
    code blocks so a `#` comment inside a code sample isn't mistaken for one."""
    out = []
    in_code = False
    for ln in lines:
        s = ln.strip()
        if s.startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        if s.startswith('### '):
            out.append((3, _toc_plain(s[4:])))
        elif s.startswith('## '):
            out.append((2, _toc_plain(s[3:])))
        elif s.startswith('# '):
            out.append((1, _toc_plain(s[2:])))
    return out


def add_table_of_contents(doc, headings):
    """A static, pre-populated outline of the document's headings.

    We deliberately do NOT use Word's TOC *field*: it renders as placeholder
    text until an application re-evaluates it, and on macOS/Linux the
    LibreOffice conversion path can't update it (and LibreOffice's embedded
    Python is launch-constraint-blocked from scripting it). A static outline
    renders identically and correctly in Word, LibreOffice, and any PDF viewer.
    Trade-off: no live page numbers — the section numbers carried in the
    heading text provide the structure instead."""
    p = doc.add_heading("Contents", level=1)
    set_paragraph_shading(p, H1_BG_HEX)

    # Drop a leading level-1 entry (the document title, already on the cover).
    entries = headings[1:] if (headings and headings[0][0] == 1) else headings
    base = min((lv for lv, _ in entries), default=1)
    for level, title in entries:
        para = doc.add_paragraph()
        para.paragraph_format.left_indent = Pt(18 * (level - base))
        para.paragraph_format.space_after = Pt(2)
        run = para.add_run(title)
        run.font.size = Pt(11)
        if level == base:
            run.font.bold = True

    add_page_break(doc)


def add_cover_page(doc):
    # Two empty paragraphs at the top push the title down a few cm
    for _ in range(2):
        doc.add_paragraph()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run(DOC_TITLE)
    tr.font.size = Pt(38)
    tr.font.color.rgb = TITLE_COLOR_RGB
    tr.bold = True

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = subtitle.add_run(DOC_SUBTITLE)
    sr.font.size = Pt(24)
    sr.font.color.rgb = SUBTITLE_COLOR_RGB
    sr.italic = True

    for _ in range(2):
        doc.add_paragraph()

    # If the project ships a PNG icon, drop it on the cover as a small mark.
    icon_path = Path('icons/dses_sa.png')
    if icon_path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(icon_path), width=Inches(1.5))

    for _ in range(3):
        doc.add_paragraph()

    # Version / author / org / date stacked at the bottom of the cover.
    # DOC_VERSION starting with 'v' renders as "Version X.Y.Z" (manuals);
    # anything else (e.g. "Rev A" for reports) is printed verbatim.
    ver_text = (f"Version {DOC_VERSION.lstrip('v')}"
                if DOC_VERSION.startswith('v') else DOC_VERSION)
    for text in (
        ver_text,
        DOC_AUTHOR,
        DOC_ORG,
        date.today().strftime("%B %Y"),
    ):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.font.size = Pt(16)
        r.font.color.rgb = SUBTITLE_COLOR_RGB
    add_page_break(doc)


def apply_heading_styles(doc):
    """Tweak the built-in heading styles to match DSES (after the doc is
    created, since python-docx populates styles from the default template)."""
    h1 = doc.styles['Heading 1']
    h1.font.color.rgb = H1_TEXT_RGB
    h1.font.size = Pt(11)
    h1.font.bold = True
    # Rick's H1 spacing tweak: 12 pt above, 6 pt below (was 24/0).
    h1.paragraph_format.space_before = Pt(12)
    h1.paragraph_format.space_after = Pt(6)
    # Heading-2 stays default (slate); Heading 3 → dark teal
    h3 = doc.styles['Heading 3']
    h3.font.color.rgb = H3_COLOR_RGB
    h3.font.bold = True

    normal = doc.styles['Normal']
    normal.font.name = 'Calibri'
    normal.font.size = Pt(11)


# ---------------------------------------------------------------------------
# Code blocks + tables (unchanged from previous version)
# ---------------------------------------------------------------------------

def add_code_block(doc, lines):
    table = doc.add_table(rows=1, cols=1)
    table.autofit = True
    cell = table.cell(0, 0)
    set_cell_shading(cell, CODE_FILL_HEX)
    cell.text = ''
    first = True
    for line in lines:
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        run = p.add_run(line)
        run.font.name = 'Consolas'
        run.font.size = Pt(9)


def add_table(doc, header_row, body_rows):
    cols = len(header_row)
    table = doc.add_table(rows=1 + len(body_rows), cols=cols)
    table.style = 'Light Grid Accent 1'
    for j, cell_text in enumerate(header_row):
        cell = table.rows[0].cells[j]
        cell.text = ''
        add_runs(cell.paragraphs[0], cell_text)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for i, row in enumerate(body_rows):
        for j in range(cols):
            cell_text = row[j] if j < len(row) else ''
            cell = table.rows[1 + i].cells[j]
            cell.text = ''
            add_runs(cell.paragraphs[0], cell_text)


def parse_table_block(lines, start):
    def split_row(s):
        s = s.strip()
        if s.startswith('|'):
            s = s[1:]
        if s.endswith('|'):
            s = s[:-1]
        return [c.strip() for c in s.split('|')]
    i = start
    header = split_row(lines[i]); i += 1
    i += 1  # alignment row
    body = []
    while i < len(lines) and lines[i].strip().startswith('|'):
        body.append(split_row(lines[i]))
        i += 1
    return header, body, i


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def md_to_docx(src_path: Path, dst_path: Path):
    text = src_path.read_text(encoding='utf-8')
    text = smartify_quotes(text)
    lines = text.split('\n')

    doc = Document()
    configure_section(doc.sections[0])
    apply_heading_styles(doc)
    add_cover_page(doc)
    add_table_of_contents(doc, collect_headings(lines))

    # Style a Heading-1 paragraph so it gets the teal banner. We do this by
    # post-processing each Heading-1 paragraph after add_heading() rather
    # than wiring it into the global style (which would also paint the TOC,
    # the cover page, etc., with shading).
    def add_h1_banner(text):
        p = doc.add_heading(text, level=1)
        set_paragraph_shading(p, H1_BG_HEX)

    i = 0
    prev_was_table = False          # for post-table paragraph spacing
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # A body paragraph immediately under a table gets a little air above
        # it (Rick's house tweak). Latch the "previous block was a table"
        # state here and clear it each iteration; only the table branch re-sets
        # it, so a heading/image between table and paragraph correctly resets.
        after_table = prev_was_table
        prev_was_table = False

        if stripped.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            add_code_block(doc, code_lines)
            continue

        if stripped.startswith('|') and i + 1 < len(lines) \
                and re.match(r'^\s*\|[\s\-:|]+\|\s*$', lines[i + 1]):
            header, body, i = parse_table_block(lines, i)
            add_table(doc, header, body)
            prev_was_table = True
            continue

        if stripped.startswith('### '):
            doc.add_heading(stripped[4:], level=3)
            i += 1; continue
        if stripped.startswith('## '):
            doc.add_heading(stripped[3:], level=2)
            i += 1; continue
        if stripped.startswith('# '):
            add_h1_banner(stripped[2:])
            i += 1; continue

        # Image: a line of the form ![caption](path). The path is resolved
        # relative to the source .md; the alt text becomes an italic caption.
        m_img = re.match(r'^!\[(.*?)\]\((.+?)\)\s*$', stripped)
        if m_img:
            caption, img_ref = m_img.group(1), m_img.group(2)
            img_path = Path(img_ref)
            if not img_path.is_absolute():
                img_path = src_path.parent / img_path
            if img_path.is_file():
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run().add_picture(str(img_path), width=Inches(6.2))
                if caption:
                    cp = doc.add_paragraph()
                    cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cr = cp.add_run(caption)
                    cr.font.size = Pt(8.5)
                    cr.font.italic = True
                    cr.font.color.rgb = SUBTITLE_COLOR_RGB
            else:
                p = doc.add_paragraph()
                add_runs(p, f"*[missing image: {img_ref}]*")
            i += 1; continue

        if re.match(r'^\s*[-*]\s+', line):
            while i < len(lines) and re.match(r'^\s*[-*]\s+', lines[i]):
                content = re.sub(r'^\s*[-*]\s+', '', lines[i])
                p = doc.add_paragraph(style='List Bullet')
                add_runs(p, content)
                i += 1
            continue

        if re.match(r'^\s*\d+\.\s+', line):
            while i < len(lines) and re.match(r'^\s*\d+\.\s+', lines[i]):
                content = re.sub(r'^\s*\d+\.\s+', '', lines[i])
                p = doc.add_paragraph(style='List Number')
                add_runs(p, content)
                while (i + 1 < len(lines) and lines[i + 1].startswith('   ')
                       and not re.match(r'^\s*\d+\.\s+', lines[i + 1])
                       and not re.match(r'^\s*[-*]\s+', lines[i + 1])
                       and lines[i + 1].strip() != ''):
                    i += 1
                    cont = lines[i].strip()
                    if cont.startswith('```'):
                        code_lines = []
                        i += 1
                        while i < len(lines) and not lines[i].strip().startswith('```'):
                            code_lines.append(lines[i].lstrip())
                            i += 1
                        add_code_block(doc, code_lines)
                    elif cont:
                        cp = doc.add_paragraph()
                        cp.paragraph_format.left_indent = Inches(0.5)
                        add_runs(cp, cont)
                i += 1
            continue

        if stripped == '':
            prev_was_table = after_table   # carry table-state across blank lines
            i += 1; continue

        # Paragraph: coalesce wrapped lines
        para_lines = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            ns = nxt.strip()
            if ns == '' or ns.startswith(('#', '-', '*', '|', '```')) \
                    or re.match(r'^\s*\d+\.\s+', nxt):
                break
            para_lines.append(nxt)
            i += 1
        p = doc.add_paragraph()
        if after_table:
            p.paragraph_format.space_before = Pt(6)
        add_runs(p, ' '.join(s.strip() for s in para_lines))

    doc.save(dst_path)
    print(f"Wrote {dst_path} ({dst_path.stat().st_size // 1024} KB)")


def _kill_stale_invisible_word():
    """Kill any orphaned background Word processes left over from a
    previous run that crashed between Documents.Open and word.Quit.
    Skipped silently if psutil isn't available."""
    try:
        import psutil
    except ImportError:
        return
    for p in psutil.process_iter(['name']):
        if (p.info.get('name') or '').lower() == 'winword.exe':
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass


def _find_soffice():
    """Locate a LibreOffice/OpenOffice headless binary, or None."""
    import shutil
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    # Common macOS install location (not on PATH by default).
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if mac.is_file():
        return str(mac)
    return None


def _convert_docx_to_pdf_soffice(soffice: str, docx_path: Path, pdf_path: Path):
    """macOS/Linux PDF path: convert via LibreOffice headless.

    Note: LibreOffice does not re-evaluate Word's TOC *field* the way Word
    does, so the table of contents may render with its placeholder text. The
    body, headings, page numbers and styling come through fine. For a fully
    populated TOC, build on Windows with Word (the path below) or open the
    .docx in Word once and Save As PDF."""
    import subprocess
    outdir = pdf_path.resolve().parent
    subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                    "--outdir", str(outdir), str(docx_path.resolve())],
                   check=True, capture_output=True, text=True)
    produced = outdir / (docx_path.stem + ".pdf")
    if produced != pdf_path.resolve():
        produced.replace(pdf_path)
    print(f"Wrote {pdf_path} ({pdf_path.stat().st_size // 1024} KB) via LibreOffice")


def convert_docx_to_pdf(docx_path: Path, pdf_path: Path):
    """Convert the DOCX to PDF using the best available engine:

      * Windows + Microsoft Word -> Word via pywin32 (updates the TOC/PAGE
        fields properly; the preferred, fully-correct path);
      * otherwise (macOS/Linux)  -> LibreOffice headless, if installed.

    Raises if neither is available so the caller can fall back to shipping
    the .docx and asking for a manual Save-As-PDF."""
    if sys.platform == "win32":
        return _convert_docx_to_pdf_word(docx_path, pdf_path)
    soffice = _find_soffice()
    if soffice:
        return _convert_docx_to_pdf_soffice(soffice, docx_path, pdf_path)
    raise RuntimeError(
        "No PDF engine found. On Windows install Microsoft Word; on "
        "macOS/Linux install LibreOffice (macOS: `brew install --cask "
        "libreoffice`) and re-run, or open the .docx and Save As PDF.")


def _convert_docx_to_pdf_word(docx_path: Path, pdf_path: Path):
    """Open the DOCX in Word, update every field (TOC + PAGE), then save
    as PDF. Direct pywin32 instead of docx2pdf so we control the field-
    update step — without it the TOC stays as the placeholder text.
    Requires Microsoft Word on Windows.

    Note: kills any leftover background winword.exe before starting. If
    you have Word open with a document you care about, save first."""
    _kill_stale_invisible_word()
    import win32com.client
    word = win32com.client.Dispatch('Word.Application')
    word.Visible = False
    try:
        doc = word.Documents.Open(str(docx_path.resolve()))
        try:
            # Update headers/footers + body fields. Run twice: the first
            # pass renders the TOC entries which can change page counts,
            # the second pass corrects the TOC's page numbers in light of
            # the new layout.
            for _ in range(2):
                doc.Fields.Update()
                # TablesOfContents may also need its own Update call on some
                # Word builds.
                try:
                    if doc.TablesOfContents.Count > 0:
                        doc.TablesOfContents(1).Update()
                except Exception:
                    pass
            # wdFormatPDF = 17
            doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)
            # Save the .docx too so the populated TOC persists for future
            # opens in Word (otherwise the TOC reverts to the placeholder).
            doc.Save()
        finally:
            doc.Close(SaveChanges=False)
    finally:
        word.Quit()
    print(f"Wrote {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")


def main():
    global DOC_TITLE, DOC_SUBTITLE  # cover-page/header read these as globals
    import argparse
    ap = argparse.ArgumentParser(
        description="Build a DSES-styled DOCX + PDF from a Markdown source.")
    ap.add_argument('src', nargs='?', default=str(SRC),
                    help=f"Markdown source (default: {SRC})")
    ap.add_argument('--docx', default=None,
                    help="Keep the intermediate DOCX at this path (default: a "
                         "temp file, removed after the PDF is built).")
    ap.add_argument('--pdf', default=str(DST_PDF),
                    help=f"PDF output path (default: {DST_PDF})")
    ap.add_argument('--title', default=DOC_TITLE,
                    help=f"Cover-page title (default: {DOC_TITLE!r})")
    ap.add_argument('--subtitle', default=DOC_SUBTITLE,
                    help=f"Cover-page + header subtitle "
                         f"(default: {DOC_SUBTITLE!r})")
    ap.add_argument('--version', default=DOC_VERSION, dest='doc_version',
                    help="Cover-page version line. A value starting with 'v' "
                         "renders as 'Version X.Y.Z'; anything else (e.g. "
                         f"'Rev A') is printed verbatim. Default: {DOC_VERSION!r}")
    ap.add_argument('--header-logo', default=None,
                    help="PNG shown right-justified in the page header "
                         "(pages 2+; the cover is unaffected). Default: none.")
    ap.add_argument('--force', action='store_true',
                    help="Overwrite the --docx target even if git reports it "
                         "modified (i.e., discard hand-made Word edits).")
    args = ap.parse_args()
    DOC_TITLE = args.title
    DOC_SUBTITLE = args.subtitle
    globals()['DOC_VERSION'] = args.doc_version
    globals()['HEADER_LOGO'] = args.header_logo

    src = Path(args.src)
    pdf_out = Path(args.pdf)
    if not src.exists():
        print(f"Source not found: {src}", file=sys.stderr)
        sys.exit(1)

    # The DOCX is a throwaway intermediate: write it to a temp file and remove
    # it after the PDF is built, unless --docx asked to keep it somewhere.
    import tempfile
    keep_docx = args.docx is not None
    if keep_docx:
        docx_out = Path(args.docx)
    else:
        docx_out = Path(tempfile.gettempdir()) / f"{pdf_out.stem}.docx"

    # GUARD: never clobber hand-made Word edits. Rebuilding regenerates the
    # DOCX from the .md, so any direct edits to a kept, git-tracked DOCX are
    # lost. If git reports the target modified vs HEAD, someone edited it
    # since the last build -- stop and make them port the edits into the .md
    # (or pass --force to overwrite deliberately). Born of the 2026-07-13
    # trip-report incident; do not remove.
    if keep_docx and docx_out.exists() and not args.force:
        import subprocess
        try:
            r = subprocess.run(
                ['git', 'status', '--porcelain', '--', str(docx_out)],
                capture_output=True, text=True, timeout=15)
            dirty = r.returncode == 0 and r.stdout.strip().startswith(' M')
        except Exception:
            dirty = False
        if dirty:
            print(f"REFUSING to overwrite {docx_out}:\n"
                  "  git says it was modified since the last commit — it "
                  "likely contains\n  hand-made Word edits that a rebuild "
                  "would destroy.\n"
                  "  Port those edits into the Markdown source first (or "
                  "commit the DOCX),\n  then rebuild. Pass --force to "
                  "overwrite anyway.", file=sys.stderr)
            sys.exit(3)

    md_to_docx(src, docx_out)
    try:
        convert_docx_to_pdf(docx_out, pdf_out)
    except Exception as exc:
        print(f"PDF conversion failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        print(f"The intermediate DOCX is at {docx_out}; open it in "
              "LibreOffice/Word and export to PDF manually.", file=sys.stderr)
        sys.exit(2)
    finally:
        if not keep_docx:
            try:
                docx_out.unlink()
            except OSError:
                pass


if __name__ == '__main__':
    main()
