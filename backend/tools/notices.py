"""Förteckning över tredjepartskomponenter och deras licenser.

Läser de Python-paket som är installerade i den aktuella miljön (bara de som
appen behöver när den körs, inte test- och utvecklingsverktyg), Pandoc,
språkresurserna och – om den anges – npm-förteckningen från
frontend/scripts/notices.mjs.

    # Fullständiga licenstexter (används vid bygget av Docker-imagen):
    python tools/notices.py --npm npm-notices.txt --out THIRD_PARTY_NOTICES.txt

    # Sammanställning för repot (THIRD_PARTY_LICENSES.md):
    python tools/notices.py --markdown ../THIRD_PARTY_LICENSES.md --npm-json npm.json
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
SV = ROOT / "resources" / "sv"
RULE = "=" * 78


def _name(req: str) -> str:
    return re.split(r"[\s;<>=!~\[]", req.strip(), maxsplit=1)[0].lower().replace("_", "-")


def runtime_distributions() -> list[md.Distribution]:
    """Paketen i requirements.txt och allt de behöver (utan extras)."""
    wanted = [_name(line) for line in REQUIREMENTS.read_text().splitlines() if line.strip() and not line.startswith("#")]
    seen: dict[str, md.Distribution] = {}
    while wanted:
        name = wanted.pop()
        if name in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        seen[name] = dist
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            if ";" in req:
                marker = req.split(";", 1)[1]
                if "python_version <" in marker or "sys_platform == \"win32\"" in marker or "platform_system == \"Windows\"" in marker:
                    continue
            wanted.append(_name(req))
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def license_of(dist: md.Distribution) -> str:
    m = dist.metadata
    expr = m.get("License-Expression")
    if expr:
        return expr
    # Licensfilen säger mer än metadata (t.ex. spylls: MPL 2.0 trots klassificeraren "MIT").
    for f in license_files(dist):
        head = f.read_text(errors="replace")[:200]
        if "Mozilla Public License" in head:
            return "MPL-2.0"
    classifiers = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    lic = (m.get("License") or "").strip()
    if classifiers:
        names = {"MIT License": "MIT", "BSD License": "BSD", "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
                 "Apache Software License": "Apache-2.0"}
        return " / ".join(names.get(c, c) for c in classifiers)
    return lic.splitlines()[0][:60] if lic and lic != "UNKNOWN" else "se licensfilen"


def license_files(dist: md.Distribution) -> list[Path]:
    files = []
    for f in dist.files or []:
        p = Path(str(f))
        if re.match(r"(licen[cs]e|copying|notice|authors)", p.name, re.I) and ".dist-info" in str(f):
            files.append(Path(dist.locate_file(f)))
    return sorted(set(files))


def pandoc_info() -> tuple[str, Path | None]:
    try:
        import pypandoc

        path = pypandoc.get_pandoc_path()
        version = subprocess.run([path, "--version"], capture_output=True, text=True, check=True).stdout.split()[1]
        copyright_file = Path(pypandoc.__file__).parent / "files" / "copyright.pandoc"
        return version, copyright_file if copyright_file.exists() else None
    except Exception:  # noqa: BLE001 – förteckningen ska kunna skrivas även utan Pandoc
        return "okänd", None


def resources() -> list[dict]:
    return [
        {
            "name": "Den stora svenska ordlistan (sv_SE.aff, sv_SE.dic)",
            "version": "dictionary-sv 4.0.0",
            "license": "LGPL-3.0",
            "url": "https://github.com/wooorm/dictionaries",
            "files": [SV / "LICENSE_sv_SE.txt", SV / "LICENSE-dictionary-sv.txt"],
        },
        {
            "name": "Synlex – Folkets synonymlexikon (th_sv_SE.dat)",
            "version": "2009, LibreOffice-konvertering (omkodad till UTF-8)",
            "license": "Synlex-licens (fri användning med bevarad upphovsrättsnotis)",
            "url": "https://github.com/LibreOffice/dictionaries",
            "files": [SV / "README_th_sv_SE.txt"],
        },
    ]


def write_notices(out: Path, npm_text: str) -> None:
    parts = [
        "Word Work – tredjepartskomponenter och licenser\n",
        "Word Work själv: Apache License 2.0, Copyright 2026 Mikke Schirén (se LICENSE).\n",
        "Fullständiga standardlicenstexter (GPL-2.0, GPL-3.0, LGPL-3.0, MPL-2.0) finns i samma mapp.\n\n",
    ]
    version, cfile = pandoc_info()
    parts.append(f"{RULE}\nPandoc {version} – GPL-2.0-or-later\nhttps://pandoc.org\n{RULE}\n")
    parts.append(
        "Pandoc körs som ett separat program (via pypandoc_binary) och är inte länkat med Word Works kod.\n"
        f"Källkod för exakt den här versionen: https://github.com/jgm/pandoc/tree/{version}\n"
        f"och https://hackage.haskell.org/package/pandoc-{version}\n"
        "Licenstext: GPL-2.0.txt i samma mapp.\n\n"
    )
    if cfile:
        parts.append(cfile.read_text(errors="replace").strip() + "\n\n")
    for r in resources():
        parts.append(f"{RULE}\n{r['name']} – {r['license']}\n{r['version']}\n{r['url']}\n{RULE}\n")
        for f in r["files"]:
            if f.exists():
                parts.append(f.read_text(errors="replace").strip() + "\n\n")
    parts.append(f"{RULE}\nPython-paket\n{RULE}\n\n")
    for dist in runtime_distributions():
        m = dist.metadata
        parts.append(f"{RULE}\n{m['Name']} {dist.version} – {license_of(dist)}\n{m.get('Home-page') or ''}\n{RULE}\n")
        files = license_files(dist)
        for f in files:
            parts.append(f.read_text(errors="replace").strip() + "\n")
        if not files:
            parts.append(f"(Ingen licensfil i paketet. Licens enligt metadata: {license_of(dist)}.)\n")
        parts.append("\n")
    if npm_text:
        parts.append(f"{RULE}\nnpm-paket i webbappen\n{RULE}\n\n{npm_text}")
    out.write_text("".join(parts))


def write_markdown(out: Path, npm_rows: list[dict]) -> None:
    version, _ = pandoc_info()
    lines = [
        "# Tredjepartskomponenter",
        "",
        "Word Work har licensen Apache 2.0 (se [LICENSE](LICENSE)), Copyright 2026 Mikke Schirén.",
        "Här listas de komponenter från tredje part som följer med i appen eller Docker-imagen, och deras licenser.",
        "Fullständiga licenstexter finns i [LICENSES/](LICENSES/). I imagen skapas förteckningen på nytt vid",
        "bygget utifrån de paket som faktiskt installeras: `/app/licenses/THIRD_PARTY_NOTICES.txt`.",
        "",
        "Skapad med `python backend/tools/notices.py --markdown …` – kör om när beroenden ändras.",
        "",
        "## Program och data",
        "",
        "| Komponent | Version | Licens | Hur den används |",
        "|---|---|---|---|",
        f"| [Pandoc](https://pandoc.org) | {version} | GPL-2.0-or-later | Separat program för import och export; följer med i imagen via pypandoc_binary. Källkod: <https://github.com/jgm/pandoc/tree/{version}> |",
        "| Den stora svenska ordlistan (Göran Andersson) | dictionary-sv 4.0.0 | LGPL-3.0 | Stavningsordlista, separata och oförändrade datafiler |",
        "| Synlex – Folkets synonymlexikon (Viggo Kann, KTH) | 2009 | Synlex-licens (fri användning, notisen ska behållas) | Synonymer; omkodad till UTF-8 |",
        "",
        "## Python-paket (backend)",
        "",
        "| Paket | Version | Licens |",
        "|---|---|---|",
    ]
    for dist in runtime_distributions():
        lines.append(f"| {dist.metadata['Name']} | {dist.version} | {license_of(dist)} |")
    lines += ["", "## npm-paket (webbappen)", "", "| Paket | Version | Licens |", "|---|---|---|"]
    for r in npm_rows:
        lines.append(f"| {r['name']} | {r['version']} | {r['license']} |")
    lines += [
        "",
        "## Grundimage",
        "",
        "Docker-imagen bygger på Chainguards Wolfi-baserade images (`cgr.dev/chainguard/python`).",
        "Operativsystempaketen i dem, bland annat Python, har egna licenser. De framgår av imagens SBOM",
        "(se *Skanning och SBOM* i README).",
        "",
    ]
    out.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="fil för fullständiga licenstexter")
    ap.add_argument("--npm", type=Path, help="npm-licenstexter från frontend/scripts/notices.mjs")
    ap.add_argument("--markdown", type=Path, help="sammanställning i Markdown")
    ap.add_argument("--npm-json", type=Path, help="npm-förteckning (notices.mjs --json)")
    a = ap.parse_args()
    if a.out:
        write_notices(a.out, a.npm.read_text() if a.npm else "")
    if a.markdown:
        write_markdown(a.markdown, json.loads(a.npm_json.read_text()) if a.npm_json else [])


if __name__ == "__main__":
    main()
