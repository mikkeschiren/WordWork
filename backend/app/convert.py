"""Import och export via Pandoc (bundlad binär från pypandoc_binary)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pypandoc

from .storage import split_frontmatter

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
TEMPLATES = RESOURCES / "templates"
FILTERS = RESOURCES / "filters"

# Pandocs markdown utan "smart" – citattecken och tankstreck ska stå exakt som
# författaren skrivit dem (svenska ” ” och –, inte engelska “ ”).
MD_IN = "markdown-smart"
# Det Markdown som editorn förstår: GFM med YAML-frontmatter, utan radbrytning.
MD_OUT = "gfm+yaml_metadata_block"
TIMEOUT = 60
MAX_IMPORT_BYTES = 25 * 1024 * 1024


class ConvertError(Exception):
    status = 400


@dataclass(frozen=True)
class ExportFormat:
    key: str
    label: str
    ext: str
    media_type: str
    pandoc: str | None  # None = ingen konvertering
    templates: bool = False


EXPORT_FORMATS: dict[str, ExportFormat] = {
    f.key: f
    for f in [
        ExportFormat(
            "docx",
            "Word (.docx)",
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
            templates=True,
        ),
        ExportFormat(
            "odt", "OpenDocument (.odt)", "odt", "application/vnd.oasis.opendocument.text", "odt", templates=True
        ),
        ExportFormat("rtf", "Rich Text (.rtf)", "rtf", "application/rtf", "rtf"),
        ExportFormat("html", "Webbsida (.html)", "html", "text/html; charset=utf-8", "html5"),
        ExportFormat("md", "Markdown (.md)", "md", "text/markdown; charset=utf-8", None),
        ExportFormat("txt", "Ren text (.txt)", "txt", "text/plain; charset=utf-8", "plain"),
    ]
}

TEMPLATE_LABELS = {
    "standard": "Standard – Cambria 12 p, rubriker i Calibri",
    "manus": "Manus – Times 12 p, 1,5 radavstånd, indrag",
    "artikel": "Artikel – Georgia 11 p, luft mellan stycken",
}

# filändelse → Pandoc-läsare (None = läses som text direkt)
IMPORT_FORMATS: dict[str, str | None] = {
    "docx": "docx",
    "odt": "odt",
    "rtf": "rtf",
    "html": "html",
    "htm": "html",
    "md": None,
    "markdown": None,
    "txt": None,
}

HTML_CSS = """
body { max-width: 40em; margin: 3em auto; padding: 0 1em; font: 18px/1.65 Georgia, serif; color: #222; }
h1, h2, h3 { line-height: 1.25; }
blockquote { margin-left: 0; padding-left: 1em; border-left: 3px solid #ddd; font-style: italic; }
header { margin-bottom: 2em; } .author, .date { margin: 0; color: #666; }
@page { size: A4; margin: 2.5cm; }
@media print { body { max-width: none; margin: 0; padding: 0; font-size: 12pt; } }
"""


def _pandoc(args: list[str], input_bytes: bytes | None = None) -> bytes:
    cmd = [pypandoc.get_pandoc_path(), *args]
    try:
        res = subprocess.run(cmd, input=input_bytes, capture_output=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ConvertError("Konverteringen tog för lång tid.") from exc
    if res.returncode != 0:
        msg = res.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ConvertError(f"Pandoc kunde inte konvertera filen: {msg[-1] if msg else 'okänt fel'}")
    return res.stdout


_FENCE = re.compile(r"^\s*(```|~~~)")


def strip_notes(md: str) -> str:
    """Tar bort egna anteckningar (HTML-kommentarer), utom i kodblock.

    En rad som bara bestod av en anteckning försvinner helt.
    """
    out: list[str] = []
    fence = in_note = False
    for line in md.split("\n"):
        if not in_note and _FENCE.match(line):
            fence = not fence
        if fence:
            out.append(line)
            continue
        was_in_note, rest, kept = in_note, line, ""
        while rest:
            if in_note:
                end = rest.find("-->")
                if end < 0:
                    rest = ""
                    break
                rest, in_note = rest[end + 3:], False
                if kept[-1:].isspace() and rest[:1].isspace():
                    rest = rest.lstrip(" \t")
            else:
                start = rest.find("<!--")
                if start < 0:
                    kept += rest
                    break
                kept, rest, in_note = kept + rest[:start], rest[start + 4:], True
        if kept.strip():
            out.append(kept.rstrip())
        elif not was_in_note and "<!--" not in line:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


def _title(frontmatter: str) -> str:
    m = re.search(r"^title:[ \t]+(.+?)[ \t]*$", frontmatter, re.M)
    if not m:
        return ""
    v = m.group(1)
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return " ".join(v.split())


def _drop_duplicate_title(frontmatter: str, body: str) -> str:
    """Pandoc skriver titeln överst. Står samma rubrik först i texten tas den bort, så den inte syns två gånger."""
    title = _title(frontmatter)
    if not title:
        return body
    m = re.match(r"\s*#[ \t]+(.+?)[ \t#]*(?:\n|$)", body)
    if m and " ".join(m.group(1).split()) == title:
        return body[m.end():].lstrip("\n")
    return body


PAGED_FORMATS = {"docx", "odt", "rtf", "html"}


def export_document(
    name: str, markdown: str, fmt_key: str, template: str = "standard", chapters: int = 0
) -> tuple[bytes, ExportFormat]:
    """Exporterar. `chapters` (1 eller 2) ger ny sida före varje rubrik på den nivån."""
    fmt = EXPORT_FORMATS.get(fmt_key)
    if fmt is None:
        raise ConvertError(f"Okänt exportformat: {fmt_key}")
    frontmatter, body = split_frontmatter(markdown)
    body = strip_notes(body)  # egna anteckningar följer aldrig med
    if fmt.pandoc is None:
        return (frontmatter + body).encode("utf-8"), fmt
    if fmt.key in {"docx", "odt", "rtf", "html"}:
        body = _drop_duplicate_title(frontmatter, body)
    args = ["-f", MD_IN, "-t", fmt.pandoc, "--wrap=none", "-M", "lang=sv-SE"]
    if chapters not in (0, 1, 2):
        raise ConvertError("Kapitelnivån måste vara 1 eller 2.")
    if chapters and fmt.key in PAGED_FORMATS:
        args += ["--lua-filter", str(FILTERS / "chapters.lua"), "-M", f"ww-chapter-level={chapters}"]
    if fmt.key in {"docx", "odt", "rtf", "html"}:
        args.append("--standalone")
    if fmt.key == "html":
        # Titel i webbläsarfliken utan att skriva in en rubrik som inte finns i texten.
        args += ["-M", f"pagetitle={name}", "-V", f"header-includes=<style>{HTML_CSS}</style>"]
    if fmt.templates:
        # Alltid en egen mall – även Standard – så att sidformatet blir A4.
        if template not in TEMPLATE_LABELS:
            raise ConvertError(f"Okänd mall: {template}")
        args += ["--reference-doc", str(TEMPLATES / f"{template}.{fmt.ext}")]
    if fmt.key == "txt":
        # Ren text: metadata hör inte hemma i brödtexten.
        markdown = body
    else:
        markdown = frontmatter + body
    data = _pandoc(args, markdown.encode("utf-8"))
    if fmt.key == "rtf":
        data = _rtf_a4(data)
    return data, fmt


# A4 (11906 × 16838 twips) med 2,5 cm (1417 twips) marginaler.
RTF_A4 = rb"\paperw11906\paperh16838\margl1417\margr1417\margt1417\margb1417" + b"\n"


def _rtf_a4(data: bytes) -> bytes:
    """Pandocs RTF saknar sidformat (Word väljer då ofta Letter) – lägg in A4."""
    marker = b"\\widowctrl"
    i = data.find(marker)
    if i < 0:  # okänd mall – lägg sidformatet efter första raden
        i = data.find(b"\n") + 1
    return data[:i] + RTF_A4 + data[i:]


def import_file(filename: str, data: bytes) -> tuple[str, str]:
    """Returnerar (föreslaget namn, Markdown)."""
    if len(data) > MAX_IMPORT_BYTES:
        raise ConvertError("Filen är för stor (max 25 MB).")
    path = Path(filename)
    ext = path.suffix.lower().lstrip(".")
    if ext not in IMPORT_FORMATS:
        supported = ", ".join(f".{e}" for e in IMPORT_FORMATS)
        raise ConvertError(f"Filtypen stöds inte. Använd {supported}.")
    stem = path.stem.strip() or "Importerad"

    reader = IMPORT_FORMATS[ext]
    if reader is None:
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return stem, _normalize(text)

    # Filen skickas via stdin – inga temporära filer behövs i containern.
    out = _pandoc(
        ["-f", reader, "-t", MD_OUT, "--standalone", "--wrap=none", "--lua-filter", str(FILTERS / "import.lua")],
        data,
    )
    return stem, _normalize(out.decode("utf-8"))


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"{text}\n" if text else ""
