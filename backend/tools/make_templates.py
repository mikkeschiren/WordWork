"""Skapar exportmallar (referensdokument för Pandoc) för DOCX och ODT.

Körs vid behov av en utvecklare – resultatet ligger incheckat i
backend/resources/templates/ och behövs inte vid bygget av imagen.

    pip install python-docx lxml
    python tools/make_templates.py

Mallarna bygger INTE på Pandocs referensdokument (som omfattas av GPL):
  - DOCX utgår från python-docx inbyggda tomma dokument (MIT-licens), och
    alla stilar som Pandoc använder definieras här.
  - ODT byggs helt från grunden.
Mallarna är därför en del av Word Work och har samma licens (Apache 2.0).
Alla har A4, 2,5 cm marginaler och sidnummer i sidfoten.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT = Path(__file__).resolve().parent.parent / "resources" / "templates"


@dataclass
class Spec:
    name: str
    font: str
    size: float  # pt
    line: float  # radavstånd, multipel
    indent_cm: float  # första-radsindrag (0 = inget)
    space_after_pt: float
    heading_font: str = ""  # tom = samma som brödtexten
    margin_cm: float = 2.5
    h1: float = 16
    h2: float = 13
    h3: float = 12

    @property
    def hfont(self) -> str:
        return self.heading_font or self.font


SPECS = [
    # Standard: Cambria i brödtexten, Calibri i rubrikerna, luft mellan stycken.
    Spec("standard", "Cambria", 12, 1.15, 0, 6, heading_font="Calibri", h1=16, h2=14, h3=12),
    # Standardmanus: Times 12 p, 1,5 radavstånd, indrag i stället för luft mellan stycken.
    Spec("manus", "Times New Roman", 12, 1.5, 1.0, 0, h1=14, h2=12, h3=12),
    # Artikel: luftig brödtext utan indrag, tydlig luft mellan stycken.
    Spec("artikel", "Georgia", 11, 1.15, 0, 8, h1=18, h2=14, h3=12),
]

MONO = "Courier New"


# ---------------- DOCX ----------------
def _set_font(style, font: str, size: float | None = None, bold: bool | None = None, italic: bool | None = False) -> None:
    style.font.name = font
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), font)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
        rfonts.attrib.pop(qn(attr), None)
    if size is not None:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if italic is not None:
        style.font.italic = italic
    style.font.color.rgb = RGBColor(0, 0, 0)


def _style(styles, name: str, base: str | None, kind=WD_STYLE_TYPE.PARAGRAPH):
    try:
        st = styles[name]
    except KeyError:
        st = styles.add_style(name, kind)
        st.quick_style = True
    if base:
        st.base_style = styles[base]
    return st


def _para(style, before: float = 0, after: float = 0, line: float | None = None, indent: float = 0,
          left: float = 0, right: float = 0, align=None, keep_next: bool = False) -> None:
    pf = style.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if line is not None:
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = line
    pf.first_line_indent = Cm(indent)
    pf.left_indent = Cm(left)
    pf.right_indent = Cm(right)
    if align is not None:
        pf.alignment = align
    pf.keep_with_next = keep_next


def _page_number_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    fld.append(run)
    p._p.append(fld)


def make_docx(spec: Spec) -> bytes:
    doc = Document()  # python-docx tomma standarddokument (MIT)
    st = doc.styles
    C = WD_ALIGN_PARAGRAPH.CENTER

    _set_font(st["Normal"], spec.font, spec.size)
    _para(st["Normal"], after=0, line=spec.line)

    body = _style(st, "Body Text", "Normal")
    _set_font(body, spec.font, spec.size)
    _para(body, after=spec.space_after_pt, line=spec.line, indent=spec.indent_cm)
    first = _style(st, "First Paragraph", "Body Text")
    _para(first, after=spec.space_after_pt, line=spec.line, indent=0)
    compact = _style(st, "Compact", "Body Text")
    _para(compact, after=0, line=spec.line, indent=0)
    block = _style(st, "Block Text", "Body Text")
    _para(block, before=6, after=6, line=1.15, left=1, right=1)

    for level in range(1, 7):
        hs = _style(st, f"Heading {level}", "Normal")
        size = {1: spec.h1, 2: spec.h2, 3: spec.h3}.get(level, spec.size)
        _set_font(hs, spec.hfont, size, bold=True)
        _para(hs, before=spec.size * 1.5, after=spec.size * 0.5, line=1.0, keep_next=True)

    title = _style(st, "Title", "Normal")
    _set_font(title, spec.hfont, spec.h1 + 6, bold=True)
    # python-docx standardtitel har en färgad linje under – ta bort den.
    ppr = title.element.get_or_add_pPr()
    for bdr in ppr.findall(qn("w:pBdr")):
        ppr.remove(bdr)
    _para(title, before=0, after=spec.size, line=1.0, align=C, keep_next=True)
    for name, size in (("Subtitle", spec.h2), ("Author", spec.size), ("Date", spec.size)):
        s = _style(st, name, "Normal")
        _set_font(s, spec.font, size, italic=(name == "Subtitle"))
        _para(s, after=spec.size * 0.5, line=1.0, align=C, keep_next=True)
    abstract = _style(st, "Abstract", "Normal")
    _set_font(abstract, spec.font, spec.size - 1)
    _para(abstract, before=6, after=12, line=1.15, left=1, right=1)

    fn = _style(st, "Footnote Text", "Normal")
    _set_font(fn, spec.font, max(8, spec.size - 2))
    _para(fn, line=1.0)
    code = _style(st, "Source Code", "Normal")
    _set_font(code, MONO, max(8, spec.size - 2))
    _para(code, line=1.0)
    verb = _style(st, "Verbatim Char", None, WD_STYLE_TYPE.CHARACTER)
    _set_font(verb, MONO, max(8, spec.size - 2))
    _set_font(_style(st, "Footer", "Normal"), spec.font, max(8, spec.size - 2))

    for section in doc.sections:
        for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            setattr(section, side, Cm(spec.margin_cm))
        section.page_width = Cm(21.0)  # A4
        section.page_height = Cm(29.7)
        _page_number_footer(section)

    # Pandoc läser bara stilarna – ta bort ev. innehåll.
    root = doc.element.body
    for child in list(root):
        if child.tag != qn("w:sectPr"):
            root.remove(child)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------- ODT ----------------
ODT_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'office:version="1.3"'
)


def _pstyle(name: str, display: str, parent: str | None, para: str = "", text: str = "", extra: str = "") -> str:
    attrs = f'style:name="{name}" style:display-name={quoteattr(display)} style:family="paragraph"'
    if parent:
        attrs += f' style:parent-style-name="{parent}"'
    inner = ""
    if para:
        inner += f"<style:paragraph-properties {para}/>"
    if text:
        inner += f"<style:text-properties {text}/>"
    return f"<style:style {attrs} {extra}>{inner}</style:style>"


def _font(name: str, size: float | None = None, bold: bool = False, italic: bool = False) -> str:
    t = f'style:font-name={quoteattr(name)} style:font-name-asian={quoteattr(name)} style:font-name-complex={quoteattr(name)}'
    if size:
        t += f' fo:font-size="{size}pt" style:font-size-asian="{size}pt" style:font-size-complex="{size}pt"'
    w = "bold" if bold else "normal"
    st = "italic" if italic else "normal"
    t += f' fo:font-weight="{w}" style:font-weight-asian="{w}" style:font-weight-complex="{w}"'
    t += f' fo:font-style="{st}" style:font-style-asian="{st}" style:font-style-complex="{st}"'
    return t


def make_odt(spec: Spec) -> bytes:
    m = f"{spec.margin_cm}cm"
    line = f"{round(spec.line * 100)}%"
    fonts = sorted({spec.font, spec.hfont, MONO})
    faces = "".join(
        f'<style:font-face style:name={quoteattr(f)} svg:font-family={quoteattr(repr(f))} '
        f'style:font-family-generic="{"modern" if f == MONO else "roman"}"/>'
        for f in fonts
    )
    small = max(8, spec.size - 2)
    styles = [
        f'<style:default-style style:family="paragraph"><style:paragraph-properties style:writing-mode="page"/>'
        f'<style:text-properties {_font(spec.font, spec.size)} fo:language="sv" fo:country="SE"/></style:default-style>',
        _pstyle("Standard", "Standard", None, extra='style:class="text"'),
        _pstyle("Text_20_body", "Text body", "Standard",
                f'fo:margin-top="0pt" fo:margin-bottom="{spec.space_after_pt}pt" fo:line-height="{line}" '
                f'fo:text-indent="{spec.indent_cm}cm"', extra='style:class="text"'),
        _pstyle("First_20_paragraph", "First paragraph", "Text_20_body", 'fo:text-indent="0cm"'),
        _pstyle("Quotations", "Quotations", "Standard",
                'fo:margin-left="1cm" fo:margin-right="1cm" fo:margin-top="6pt" fo:margin-bottom="6pt" '
                'fo:line-height="115%" fo:text-indent="0cm"', extra='style:class="html"'),
        _pstyle("Heading", "Heading", "Standard",
                f'fo:margin-top="{spec.size * 1.5}pt" fo:margin-bottom="{spec.size * 0.5}pt" fo:keep-with-next="always"',
                _font(spec.hfont, None, bold=True), extra='style:next-style-name="Text_20_body" style:class="text"'),
    ]
    for level in range(1, 7):
        size = {1: spec.h1, 2: spec.h2, 3: spec.h3}.get(level, spec.size)
        styles.append(_pstyle(f"Heading_20_{level}", f"Heading {level}", "Heading", "", _font(spec.hfont, size, bold=True),
                              extra=f'style:default-outline-level="{level}" style:next-style-name="Text_20_body" style:class="text"'))
    styles += [
        _pstyle("Title", "Title", "Heading", 'fo:text-align="center" fo:margin-top="0pt"',
                _font(spec.hfont, spec.h1 + 6, bold=True), extra='style:class="chapter"'),
        _pstyle("Subtitle", "Subtitle", "Heading", 'fo:text-align="center"', _font(spec.font, spec.h2, italic=True),
                extra='style:class="chapter"'),
        _pstyle("Author", "Author", "Standard", 'fo:text-align="center" fo:margin-bottom="4pt"', _font(spec.font, spec.size)),
        _pstyle("Date", "Date", "Standard", 'fo:text-align="center" fo:margin-bottom="12pt"', _font(spec.font, spec.size)),
        _pstyle("Abstract", "Abstract", "Standard", 'fo:margin-left="1cm" fo:margin-right="1cm" fo:margin-bottom="12pt"',
                _font(spec.font, spec.size - 1)),
        _pstyle("Footnote", "Footnote", "Standard", 'fo:margin-left="0.5cm" fo:text-indent="-0.5cm"',
                _font(spec.font, small), extra='style:class="extra"'),
        _pstyle("Preformatted_20_Text", "Preformatted Text", "Standard", 'fo:margin-top="0pt" fo:margin-bottom="0pt"',
                _font(MONO, small), extra='style:class="html"'),
        _pstyle("Footer", "Footer", "Standard", 'fo:text-align="center"', _font(spec.font, small), extra='style:class="extra"'),
        # Sidbrytning före kapitel vid export (filters/chapters.lua): ett tomt stycke, 1 pt högt, som avslutar sidan.
        _pstyle("Pagebreak", "Pagebreak", "Standard",
                'fo:break-after="page" fo:margin-top="0cm" fo:margin-bottom="0cm" fo:line-height="100%"', 'fo:font-size="1pt"'),
        '<style:style style:name="Internet_20_link" style:display-name="Internet link" style:family="text">'
        '<style:text-properties fo:color="#1a4f8a" style:text-underline-style="solid" style:text-underline-width="auto" '
        'style:text-underline-color="font-color"/></style:style>',
    ]
    styles_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-styles {ODT_NS}>'
        f"<office:font-face-decls>{faces}</office:font-face-decls>"
        f'<office:styles>{"".join(styles)}</office:styles>'
        '<office:automatic-styles><style:page-layout style:name="pm1">'
        f'<style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" style:print-orientation="portrait" '
        f'fo:margin-top="{m}" fo:margin-bottom="{m}" fo:margin-left="{m}" fo:margin-right="{m}"/>'
        '<style:header-style/><style:footer-style><style:header-footer-properties fo:min-height="0.6cm" fo:margin-top="0.4cm"/>'
        "</style:footer-style></style:page-layout></office:automatic-styles>"
        '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1">'
        '<style:footer><text:p text:style-name="Footer"><text:page-number text:select-page="current">1</text:page-number>'
        "</text:p></style:footer></style:master-page></office:master-styles></office:document-styles>"
    )
    content_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ODT_NS}>'
        "<office:automatic-styles/><office:body><office:text>"
        '<text:p text:style-name="Standard"/></office:text></office:body></office:document-content>'
    )
    meta_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-meta {ODT_NS}><office:meta>'
        "<meta:generator>Word Work</meta:generator></office:meta></office:document-meta>"
    )
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
        '<manifest:file-entry manifest:full-path="/" manifest:version="1.3" '
        'manifest:media-type="application/vnd.oasis.opendocument.text"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>'
        '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>'
        "</manifest:manifest>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        # mimetype måste ligga först och okomprimerad
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        for name, data in (("content.xml", content_xml), ("styles.xml", styles_xml), ("meta.xml", meta_xml),
                           ("META-INF/manifest.xml", manifest)):
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data, compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in SPECS:
        (OUT / f"{spec.name}.docx").write_bytes(make_docx(spec))
        (OUT / f"{spec.name}.odt").write_bytes(make_odt(spec))
        print("skapade", spec.name)


if __name__ == "__main__":
    main()
