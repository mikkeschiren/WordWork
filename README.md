# Word Work

En lugn, distraktionsfri ordbehandlare för kulturjournalister och författare. Den körs lokalt i en Docker-container (Chainguard/Wolfi) och används i webbläsaren.

Se [PLAN.md](PLAN.md) för målbilden och [PROJEKTPLAN.md](PROJEKTPLAN.md) för arkitektur och faser.

## Kom igång

Du behöver Docker (t.ex. Docker Desktop eller OrbStack).

```sh
docker compose up -d --build
```

Öppna sedan <http://localhost:8080>.

Texterna sparas som vanliga Markdown-filer i mappen `./data` bredvid projektet. Ange en annan mapp med `WW_DATA_PATH`:

```sh
WW_DATA_PATH=~/Dokument/Texter docker compose up -d
```

## Så fungerar det

- **Skriv / Markdown.** Växla vy med knapparna högst upp eller med ⌘/ (Ctrl+/ i Windows och Linux).
  - I Skriv-vyn ser du formateringen: rubriker, fetstil, kursiv, citat och listor.
  - I Markdown-vyn ser du källtexten.
- **Metadata** kan ligga som YAML-frontmatter (`---` … `---`) först i filen. Den visas och redigeras i Markdown-vyn, döljs i Skriv-vyn och räknas inte i ord eller analys.
- **Allt är Markdown.** Endast formatering som Markdown kan uttrycka går att använda. Det finns inga typsnitt, färger eller understrykningar i själva texten. Klistrar du in formaterad text rensas sådant bort.
- **Typsnitt och tema** väljs under *Utseende* och gäller alltid hela texten. Du kan också ställa in storlek, radavstånd, textbredd, dimning av andra stycken och skrivmaskinsläge.
- **Autospar** sker strax efter att du slutat skriva.
- **Versioner:** ⌘S (Ctrl+S) sparar och lägger en version i historiken. Dessutom sparas en automatisk version högst var femte minut.
  - Under *Historik* kan du förhandsgranska en version, jämföra den med nuvarande text och återställa den.
  - En återställning sparar först den nuvarande texten, så inget går förlorat.
- **Borttagna dokument** flyttas till `data/.trash/` och kan återskapas därifrån.
- **Gränssnittet tonas bort** medan du skriver och kommer tillbaka när du rör musen.
- **Stavningskontroll** (svensk Hunspell-ordlista) stryker under okända ord i Skriv-vyn.
  - Högerklicka på ett ord för rättningsförslag, *Lägg till i egen ordlista* eller *Ignorera*.
  - Den egna ordlistan sparas i `data/.wordwork/ordlista.txt`. Under *Utseende → Egen ordlista* kan du lägga till, söka och ta bort poster, klicka på en post för att ändra den, eller redigera hela listan som text. Ändrar du filen direkt läses den in igen automatiskt.
  - **Fraser** för utländska uttryck, till exempel "open source" eller "New York Times", godkänns bara när orden står tillsammans. "open" ensamt räknas fortfarande som stavfel. I "open source-licensen" kontrolleras "licensen" som vanligt.
    - Högerklicka på två eller flera understrukna ord i rad, eller markera frasen och högerklicka. Välj sedan *Lägg till fras i egen ordlista*.
    - Frasen kan också skrivas in direkt under *Egen ordlista*.
  - I Markdown-vyn används webbläsarens egen stavningskontroll. Shift+högerklick ger webbläsarens vanliga meny.
- **Synonymer:** högerklicka på valfritt ord. Är ordet böjt visas även synonymer till grundformen. Ordet byts bara om du klickar på en synonym.
- **Analys** (knappen *Analys* eller LIX-värdet i statusraden):
  - LIX med tolkningsskala enligt lix.se, OVIX, ord per mening, andel långa ord och lästid.
  - De vanligaste orden. Klicka på ett ord för att markera alla förekomster i texten.
  - De längsta meningarna. Klicka för att hoppa till en mening.
  - Markerar du minst några ord gäller analysen bara markeringen.
- **Exportera** (knappen *Exportera* eller ⌘E / Ctrl+E) till Word (.docx), OpenDocument (.odt), RTF, HTML, Markdown eller ren text.
  - Alla exporter har A4-format. Word, OpenDocument och RTF har 2,5 cm marginaler, och HTML skrivs ut på A4.
  - För Word och OpenDocument finns tre mallar, alla med sidnummer: *Standard* (Pandocs typsnitt), *Manus* (Times 12 p, 1,5 radavstånd, indrag) och *Artikel* (Georgia 11 p, luft mellan stycken).
  - `title` och `author` i frontmatter blir dokumentegenskaper. Dokumentets språk sätts till svenska.
  - Citattecken och tankstreck exporteras exakt som du skrivit dem.
- **Importera** DOCX, ODT, RTF, HTML, Markdown och text via *Dokument → Importera …*, eller genom att släppa filer i fönstret.
  - Formatering som inte finns i Markdown (understrykning, typsnitt, färger) tas bort. Bilder tas bort.
  - Tabeller blir ett stycke per rad. Fotnoter blir upphöjda siffror med en lista *Fotnoter* sist.
  - Titel och författare från dokumentet hamnar i frontmatter.
- **AI-assistent** (knappen *AI* eller ⌘J / Ctrl+J) via Ollama:
  - AI:n **föreslår men skriver aldrig i texten**. Det finns ingen knapp som infogar AI-text, och svaren visas bara i panelen.
  - Snabbval: granska språket, hitta upprepningar, stramare text, struktur och dramaturgi, fakta att kontrollera. Du kan också ställa egna frågor och följdfrågor.
  - Markera minst några ord för att frågan ska gälla just det avsnittet.
  - Citat i svaren som finns i texten är klickbara och markerar stället i texten.
  - *Tänk efter först* låter modellen resonera innan den svarar. Det ger träffsäkrare svar men tar längre tid. Resonemanget kan visas.
  - Modell väljs i panelen. Listan hämtas från Ollama-servern.
  - Används en extern server står det i panelen, eftersom texten då lämnar datorn.
  - Går Ollama-servern inte att nå, eller saknar den chattmodell, fungerar allt annat som vanligt. AI-knappen döljs då och visas igen när servern svarar. Appen kontrollerar detta varje minut och när fönstret får fokus.

| Kortkommando | Gör |
|---|---|
| ⌘S / Ctrl+S | Spara och skapa version |
| ⌘/ / Ctrl+/ | Växla Skriv/Markdown |
| ⌘O / Ctrl+O | Öppna dokumentlistan |
| ⌘E / Ctrl+E | Exportera |
| ⌘J / Ctrl+J | AI-assistent |
| Esc | Stäng paneler |

## Konfiguration

| Variabel | Standard | Beskrivning |
|---|---|---|
| `WW_DATA_PATH` | `./data` | Mapp på din dator för texterna (compose) |
| `WW_SNAPSHOT_MINUTES` | `5` | Minsta tid mellan automatiska versioner |
| `WW_OLLAMA_URL` | `https://ollama.dglive.net` | Ollama-instans. Lokal Ollama: `http://host.docker.internal:11434`. Tom sträng (`WW_OLLAMA_URL=`) stänger av AI-stödet. |
| `WW_OLLAMA_MODEL` | `qwen3.6:35b` | Förvald modell (kan bytas i AI-panelen) |

## Utveckling

```sh
# Backend – API på :8080
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
WW_DATA_DIR=../data .venv/bin/uvicorn app.main:create_app --factory --reload --port 8080
.venv/bin/python -m pytest -q          # tester

# Frontend – Vite på :5173 (proxar /api till :8080)
cd frontend
npm ci
npm run dev
npm run build                          # typkontroll + produktionsbygge
```

- **Backend:** Python, FastAPI (`backend/app`)
- **Frontend:** TypeScript, Vite, TipTap 3 med `@tiptap/markdown` (`frontend/src`)
- **API-dokumentation:** <http://localhost:8080/api/docs>
- **Exportmallar** skapas med `backend/tools/make_templates.py` och ligger i `backend/resources/templates/`.
- **Importfiltret** (Lua) finns i `backend/resources/filters/import.lua`.

### Lagringsformat

```
data/
  Min text.md                       ← aktuellt dokument
  .history/Min text/index.json      ← versioner (metadata)
  .history/Min text/<tidsstämpel>.md
  .trash/                           ← borttagna dokument
```

## Licenser

- **Typsnitt:** Literata, Source Sans 3 och IBM Plex Mono, SIL Open Font License 1.1, via Fontsource.
- **Stavningsordlista:** "Den stora svenska ordlistan" av Göran Andersson, GNU LGPL 3.0.
- **Synonymer:** Synlex (Folkets synonymlexikon) av Viggo Kann, KTH, i LibreOffice-konvertering.
- **Stavningsmotor:** spylls (MPL 2.0).
- **Konvertering:** Pandoc (GPL 2+), som körs som separat program via pypandoc_binary.

Se `backend/resources/sv/SOURCES.txt` för källor och licenstexter.
