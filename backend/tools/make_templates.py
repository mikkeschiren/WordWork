"""Skapar exportmallar (referensdokument för Pandoc) för DOCX och ODT.

Körs vid behov av en utvecklare – resultatet ligger incheckat i
backend/resources/templates/ och behövs inte vid bygget av imagen.

    pip install python-docx lxml pypandoc_binary
    python tools/make_templates.py

Mallarna utgår från Pandocs egna referensdokument, så alla stilnamn som
Pandoc använder finns kvar. Alla mallar – även Standard – har A4 och
sidnummer; Pandocs egna referensdokument är i amerikanskt Letter-format.
"""

from __future__ import annotations

import io
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pypandoc
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from lxml import etree

OUT = Path(__file__).resolve().parent.parent / "resources" / "templates"


@dataclass
class Spec:
    name: str
    font: str
    size: float  # pt
    line: float  # radavstånd, multipel
    indent_cm: float  # första-radsindrag (0 = inget)
    space_after_pt: float
    margin_cm: float = 2.5
    restyle: bool = True  # False = behåll Pandocs typsnitt, sätt bara A4/marginaler/sidnummer
    h1: float = 16
    h2: float = 13
    h3: float = 12


SPECS = [
    # Standard: Pandocs eget utseende, men A4 (svensk standard) och sidnummer.
    Spec("standard", "", 0, 0, 0, 0, restyle=False),
    # Standardmanus: Times 12 p, 1,5 radavstånd, indrag i stället för luft mellan stycken.
    Spec("manus", "Times New Roman", 12, 1.5, 1.0, 0, h1=14, h2=12, h3=12),
    # Artikel: luftig brödtext utan indrag, tydlig luft mellan stycken.
    Spec("artikel", "Georgia", 11, 1.15, 0, 8, h1=18, h2=14, h3=12),
]


def default_reference(kind: str) -> bytes:
    pandoc = pypandoc.get_pandoc_path()
    return subprocess.run(
        [pandoc, "--print-default-data-file", f"reference.{kind}"], check=True, capture_output=True
    ).stdout


# ---------------- DOCX ----------------
def _set_font(style, font: str, size: float | None = None, bold: bool | None = None) -> None:
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
    style.font.color.rgb = None
    color = rpr.find(qn("w:color"))
    if color is not None:
        rpr.remove(color)


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
    doc = Document(io.BytesIO(default_reference("docx")))
    styles = doc.styles
    if spec.restyle:

        for name in ("Normal", "Body Text", "First Paragraph", "Compact", "Block Text", "Footnote Text"):
            if name in [s.name for s in styles]:
                _set_font(styles[name], spec.font, spec.size)

        for name in ("Body Text", "First Paragraph"):
            pf = styles[name].paragraph_format
            pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            pf.line_spacing = spec.line
            pf.space_before = Pt(0)
            pf.space_after = Pt(spec.space_after_pt)
            pf.first_line_indent = Cm(spec.indent_cm) if name == "Body Text" else Cm(0)

        bt = styles["Block Text"].paragraph_format
        bt.left_indent = Cm(1)
        bt.right_indent = Cm(1)
        bt.line_spacing = 1.15
        bt.space_before = Pt(6)
        bt.space_after = Pt(6)
        styles["Block Text"].font.italic = False

        for name, size in (("Heading 1", spec.h1), ("Heading 2", spec.h2), ("Heading 3", spec.h3)):
            _set_font(styles[name], spec.font, size, bold=True)
            styles[name].font.italic = False
            pf = styles[name].paragraph_format
            pf.space_before = Pt(spec.size * 1.5)
            pf.space_after = Pt(spec.size * 0.5)
            pf.keep_with_next = True
        for name in ("Heading 4", "Heading 5", "Heading 6"):
            _set_font(styles[name], spec.font, spec.size, bold=True)

        for name, size in (("Title", spec.h1 + 6), ("Subtitle", spec.h2), ("Author", spec.size), ("Date", spec.size)):
            if name in [s.name for s in styles]:
                _set_font(styles[name], spec.font, size, bold=(name == "Title"))

    for section in doc.sections:
        for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            setattr(section, side, Cm(spec.margin_cm))
        section.page_width = Cm(21.0)  # A4
        section.page_height = Cm(29.7)
        _page_number_footer(section)

    # Pandoc läser bara stilarna – ta bort exempeltexten i referensdokumentet.
    body = doc.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------- ODT ----------------
NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
}


def q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def _child(parent, prefix: str, name: str):
    el = parent.find(f"{prefix}:{name}", NS)
    if el is None:
        el = etree.SubElement(parent, q(prefix, name))
    return el


def make_odt(spec: Spec) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(default_reference("odt")))
    root = etree.fromstring(src.read("styles.xml"))

    # Typsnittsdeklaration
    if spec.restyle:
        decls = root.find("office:font-face-decls", NS)
        face = etree.SubElement(decls, q("style", "font-face"))
        face.set(q("style", "name"), spec.font)
        face.set(q("svg", "font-family"), f"'{spec.font}'")
        face.set(q("style", "font-family-generic"), "roman")

    def text_props(style_el, size: float | None = None, bold: bool = False):
        tp = _child(style_el, "style", "text-properties")
        for attr in ("font-name", "font-name-asian", "font-name-complex"):
            tp.set(q("style", attr), spec.font)
        if size is not None:
            for a in (q("fo", "font-size"), q("style", "font-size-asian"), q("style", "font-size-complex")):
                tp.set(a, f"{size}pt")
        if bold:
            for a in (q("fo", "font-weight"), q("style", "font-weight-asian"), q("style", "font-weight-complex")):
                tp.set(a, "bold")
            # Pandocs standardmall har kursiv rubrik 2 – vi vill ha rak.
            for a in (q("fo", "font-style"), q("style", "font-style-asian"), q("style", "font-style-complex")):
                tp.set(a, "normal")
        return tp

    def para_props(style_el, **attrs):
        pp = style_el.find("style:paragraph-properties", NS)
        if pp is None:
            pp = etree.Element(q("style", "paragraph-properties"))
            style_el.insert(0, pp)
        for k, v in attrs.items():
            prefix, _, local = k.partition("_")
            pp.set(q(prefix, local.replace("_", "-")), v)
        return pp

    def style(name: str, family: str = "paragraph", parent: str = "Standard"):
        for el in root.iter(q("style", "style")):
            if el.get(q("style", "name")) == name and el.get(q("style", "family")) == family:
                return el
        styles = root.find("office:styles", NS)
        el = etree.SubElement(styles, q("style", "style"))
        el.set(q("style", "name"), name)
        el.set(q("style", "family"), family)
        el.set(q("style", "parent-style-name"), parent)
        return el

    if spec.restyle:
        default = next(
            el for el in root.iter(q("style", "default-style")) if el.get(q("style", "family")) == "paragraph"
        )
        text_props(default, spec.size)

        line = f"{round(spec.line * 100)}%"
        after = f"{spec.space_after_pt}pt"
        para_props(style("Text_20_body", parent="Standard"), fo_margin_top="0pt", fo_margin_bottom=after,
                   fo_line_height=line, fo_text_indent=f"{spec.indent_cm}cm")
        para_props(style("First_20_paragraph", parent="Text_20_body"), fo_text_indent="0cm")
        para_props(style("Quotations", parent="Standard"), fo_margin_left="1cm", fo_margin_right="1cm",
                   fo_margin_top="6pt", fo_margin_bottom="6pt", fo_line_height="115%", fo_text_indent="0cm")
        text_props(style("Heading", parent="Standard"))
        for level, size in ((1, spec.h1), (2, spec.h2), (3, spec.h3)):
            h = style(f"Heading_20_{level}", parent="Heading")
            text_props(h, size, bold=True)
            para_props(h, fo_margin_top=f"{spec.size * 1.5}pt", fo_margin_bottom=f"{spec.size * 0.5}pt",
                       fo_keep_with_next="always")
        text_props(style("Title", parent="Heading"), spec.h1 + 6, bold=True)

    # Sidbrytning före kapitel vid export (filters/chapters.lua): ett tomt stycke,
    # 1 pt högt, som avslutar sidan.
    pb = style("Pagebreak", parent="Standard")
    para_props(pb, fo_break_after="page", fo_margin_top="0cm", fo_margin_bottom="0cm", fo_line_height="100%")
    pb_text = _child(pb, "style", "text-properties")
    pb_text.set(q("fo", "font-size"), "1pt")

    # Sidlayout: A4, marginaler och sidnummer i sidfoten.
    m = f"{spec.margin_cm}cm"
    auto = root.find("office:automatic-styles", NS)
    layout = auto.find("style:page-layout", NS)
    lp = _child(layout, "style", "page-layout-properties")
    for k, v in (("page-width", "21cm"), ("page-height", "29.7cm"), ("margin-top", m),
                 ("margin-bottom", m), ("margin-left", m), ("margin-right", m)):
        lp.set(q("fo", k), v)
    fstyle = _child(layout, "style", "footer-style")
    hfp = _child(fstyle, "style", "header-footer-properties")
    hfp.set(q("fo", "min-height"), "0.6cm")
    hfp.set(q("fo", "margin-top"), "0.4cm")

    footer_style = style("Footer", parent="Standard")
    para_props(footer_style, fo_text_align="center")
    master = root.find("office:master-styles/style:master-page", NS)
    for old in master.findall("style:footer", NS):
        master.remove(old)
    footer = etree.SubElement(master, q("style", "footer"))
    p = etree.SubElement(footer, q("text", "p"))
    p.set(q("text", "style-name"), "Footer")
    num = etree.SubElement(p, q("text", "page-number"))
    num.set(q("text", "select-page"), "current")
    num.text = "1"

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        # mimetype måste ligga först och okomprimerad
        dst.writestr(zipfile.ZipInfo("mimetype"), src.read("mimetype"), compress_type=zipfile.ZIP_STORED)
        for info in src.infolist():
            if info.filename == "mimetype":
                continue
            data = src.read(info.filename)
            if info.filename == "styles.xml":
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
            dst.writestr(info.filename, data, compress_type=zipfile.ZIP_DEFLATED)
    return out.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in SPECS:
        (OUT / f"{spec.name}.docx").write_bytes(make_docx(spec))
        (OUT / f"{spec.name}.odt").write_bytes(make_odt(spec))
        print("skapade", spec.name)


if __name__ == "__main__":
    main()
