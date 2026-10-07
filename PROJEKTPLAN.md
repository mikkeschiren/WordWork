# Word Work – Projektplan

Baserad på `PLAN.md`. Målet är en distraktionsfri ordbehandlare för kulturjournalister och författare, som körs som en Docker-container (Wolfi/Chainguard) och används via webbläsaren.

---

## 1. Arkitekturbeslut

| Område | Val | Motivering |
|---|---|---|
| Leveransform | Webbapp i container, öppnas på `http://localhost:8080` | Docker passar en server + webbläsare bättre än en skrivbordsapp (ingen X11/GUI i containern). |
| Backend | **Python 3.13 + FastAPI** | Bäst ekosystem för svensk språkteknik (Hunspell, lexikon, textstatistik) och enkel integration med Pandoc och Ollama. |
| Frontend | **TypeScript + Vite + TipTap 3 (ProseMirror)** med `@tiptap/markdown` | WYSIWYG-lik redigering med Markdown som lagringsformat. Växling till ren Markdown-vy (källtext). |
| Dokumentformat | Markdown internt | Enkelt, framtidssäkert, konverterbart till allt annat. |
| Export/import | **Pandoc** (via `pypandoc_binary`, bundlad binär) | Markdown → DOCX, ODT, RTF, HTML och import från DOCX/ODT. Ingen PDF i v1. Bundlad binär gör oss oberoende av Wolfi-paket. |
| Stavning | **Hunspell-format** + svensk ordlista (`sv_SE`, LibreOffice/DSSO) via `spylls` (ren Python) | Klarar svenska sammansättningar bättre än rena JS-alternativ; inga systempaket behövs. |
| Synonymer | **Synlex (Folkets synonymlexikon, KTH)** i LibreOffice/MyThes-format | Fritt svenskt synonymlexikon; ligger i repot och läses in i minnet vid start. |
| AI | **Ollama** – lokal eller extern instans, via backend-proxy | Texten stannar hos användaren. Adress och modell väljs via miljövariabel. |
| Lagring | Filer i monterad volym `/data` (Markdown) + ögonblicksbilder i `/data/.history/` | Användaren äger sina filer, enkel backup, versionshistorik. |
| Användare | **Lokal enanvändarapp** | Ingen inloggning; containern binds till `127.0.0.1`. |
| Container | Multi-stage build: `cgr.dev/chainguard/node` (bygga frontend) → `cgr.dev/chainguard/python` (runtime) | Minimal, säker image enligt kravet på Wolfi. |

```
┌───────────── Webbläsare ─────────────┐
│  Editor (CodeMirror)  │  Sidopaneler │
│  fokusläge, tema      │  LIX, ord-   │
│                       │  frekvens,   │
│                       │  synonymer,  │
│                       │  AI-chatt    │
└──────────────┬───────────────────────┘
               │ REST / SSE
┌──────────────▼─────── Container (Wolfi) ─┐
│ FastAPI                                   │
│  /spell  /synonyms  /stats  /export       │
│  /documents  /history  /ai/chat           │
│ Hunspell · Synlex · Pandoc                │
└──────────────┬────────────────────────────┘
               │ volym /data      → Ollama (lokal/extern)
```

---

## 2. Funktionalitet i detalj

### Gränssnitt (FocusWriter-stil)
- Helskärm, centrerad textkolumn med justerbar bredd, inga synliga verktygsfält.
- Paneler och menyer visas först när muspekaren når kanten eller via kortkommando.
- Teman: ljust, mörkt, sepia; val av typsnitt (serif/sans/mono), radavstånd.
- **Ett typsnitt för hela dokumentet.** Typsnitt är ett temaval, inte formatering i texten. Även i WYSIWYG-vyn kan bara Markdown-formatering användas (rubrik, fet, kursiv, citat, listor, länkar) – inga typsnitt, färger eller understrykning. Inklistrad formatering som inte är Markdown rensas bort. Filen på disk är alltid textens ”original”-Markdown.
- Valfritt: typewriter-scrolling (aktuell rad i mitten), dimning av övriga stycken.
- Statusrad (döljbar): antal ord, tecken, LIX, mål för dagen (”1 000 ord”).
- Två vyer som man växlar mellan (Ctrl/Cmd+/): **Skriv** (WYSIWYG – rubriker, fetstil, kursiv, citat, listor renderas) och **Markdown** (källtext). Markdown-genvägar (`# `, `**`, `> `) fungerar även i Skriv-vyn.
- Autospar var några sekunder + manuellt spara (Ctrl/Cmd+S).

### Versionshistorik
- Automatisk ögonblicksbild när innehållet ändrats och minst 5 minuter gått sedan förra, samt vid manuell sparning (Ctrl/Cmd+S).
- Manuell namngiven version (”Skickat till redaktör”).
- Historikpanel: lista versioner, förhandsgranska, jämför mot aktuell text, återställ (återställning skapar själv en ny version – inget går förlorat).

### Stavningskontroll
- Röd vågig understrykning av okända ord, debouncad kontroll av synliga stycken.
- Högerklick: förslag, ”Lägg till i egen ordlista”, ”Ignorera”.
- Personlig ordlista sparas i `/data` (viktigt för namn och facktermer i kulturjournalistik).

### Synonymer
- Högerklicka på ett ord → meny med synonymer (även för grundformen om ordet är böjt).
- Byte sker bara när användaren klickar.

### LIX och läsbarhet
- LIX = (ord / meningar) + (långa ord > 6 tecken × 100 / ord).
- Visas med tolkningsskala enligt lix.se (< 25 mycket lätt … > 60 mycket svår).
- Komplement: OVIX (ordvariation), nominalkvot, genomsnittlig meningslängd, längsta meningar markerade.
- Gäller hela dokumentet eller markerat avsnitt.

### Ordfrekvens / textstatistik (jfr prefix.nu)
- Antal ord, unika ord, tecken med/utan blanksteg, meningar, stycken.
- Topplista över vanligaste ord, med möjlighet att filtrera bort stoppord.
- Klick på ett ord markerar alla förekomster i texten – bra för att hitta upprepningar.
- Uppskattad lästid.

### Spara/exportera
- Internt: `.md`.
- Export: Markdown, DOCX, ODT, RTF, HTML, ren text. PDF ingår inte i v1.
- Import: DOCX, ODT, MD, TXT.

### AI-assistent (endast förslag)
- Chattpanel vid sidan av texten; användaren kan skicka hela texten eller ett markerat stycke som kontext.
- Snabbval: ”Kommentera språket”, ”Hitta upprepningar”, ”Föreslå stramare formuleringar”, ”Kontrollera faktapåståenden att verifiera”.
- **Regel: AI skriver aldrig i dokumentet.** Tekniskt säkerställt genom att:
  - AI-endpoints har inga rättigheter mot dokument-API:t.
  - Frontend saknar ”infoga”-knapp; förslag visas som kommentarer i panelen (ev. före/efter-vy) och användaren skriver om själv.
  - Systemprompten instruerar modellen att resonera och föreslå, inte leverera färdigskriven text i längre stycken.
- Körs mot Ollama (`WW_OLLAMA_URL`), lokalt eller på en extern server. Ingen Ollama-adress = ingen AI-panel. Om adressen pekar på en extern server visas en tydlig upplysning om att texten lämnar datorn.
- Modellval i inställningar (lista hämtas från Ollamas `/api/tags`).

---

## 3. Faser och leveranser

### Fas 0 – Förstudie och skelett (≈ 1 vecka)
- Endast Chainguards Python- och Node-images används; Pandoc och Hunspell-motor kommer som pip-paket, så inga Wolfi-systempaket behövs.
- Licenskoll: svensk Hunspell-ordlista (LGPL), Synlex (fri licens med krav på upphovsnotis) – se `backend/resources/sv/SOURCES.txt`.
- Repo-struktur: `backend/`, `frontend/`, `Dockerfile`, `docker-compose.yml`, CI (GitHub Actions: lint, test, build image).
- **Leverans:** `docker compose up` visar ”Hello Word Work” i webbläsaren.

### Fas 1 – Kärneditor (≈ 2 veckor)
- CodeMirror 6 med Markdown, fokusläge, teman, typsnitt.
- Dokument-API: lista, öppna, spara, autospar, byt namn, ta bort (mot `/data`).
- Ord- och teckenräkning i statusrad.
- WYSIWYG/Markdown-växling.
- Versionshistorik (ögonblicksbilder, återställ).
- **Leverans:** Fullt användbar distraktionsfri editor med lagring och historik.

### Fas 2 – Språkverktyg (≈ 2–3 veckor)
- Stavningskontroll med egen ordlista.
- Synonymer i högerklicksmenyn (Synlex).
- LIX/OVIX/nominalkvot och ordfrekvenspanel.
- **Leverans:** Alla språkfunktioner utom AI.

### Fas 3 – Import/export (≈ 1 vecka)
- Pandoc-integration för MD, DOCX, ODT, RTF, HTML, TXT (ingen PDF). Dra och släpp för import.
- Enkla exportmallar (typsnitt, marginaler) för DOCX/ODT, t.ex. ”manus” och ”artikel”.
- **Leverans:** Text kan lämnas till redaktion/förlag i deras format.

### Fas 4 – AI-assistent (≈ 2 veckor)
- Ollama-klient (lokal eller extern), modellval.
- Chattpanel med strömmande svar (SSE), snabbval, kontext från markering.
- Systemprompt och tester som säkerställer ”bara förslag”.
- **Leverans:** AI-stöd som respekterar författarens text.

### Fas 5 – Polering och release (≈ 1 vecka)
- Kortkommandon, tillgänglighet (kontrast, tangentbordsnavigering).
- Prestanda med långa manus (100 000+ ord): stavning/statistik i bakgrund och på synliga delar.
- Säkerhet: port binds till `127.0.0.1`; image-skanning (Grype/Trivy), SBOM.
- Dokumentation: README, konfiguration, backup.
- **Leverans:** v1.0 publicerad som image.

**Totalt: ca 9–11 veckor** för en utvecklare på deltid/heltid beroende på ambition.

---

## 4. Konfiguration (miljövariabler)

| Variabel | Exempel | Beskrivning |
|---|---|---|
| `WW_DATA_DIR` | `/data` | Dokument och egna ordlistor |
| `WW_OLLAMA_URL` | `https://ollama.dglive.net` | Ollama-instans (tom = AI av) |
| `WW_OLLAMA_MODEL` | `qwen3.6:35b` | Förvald modell |
| `WW_SNAPSHOT_MINUTES` | `5` | Minsta tid mellan automatiska ögonblicksbilder |

---

## 5. Risker

| Risk | Åtgärd |
|---|---|
| `spylls` för långsam på stora texter | Kontroll endast av ändrade stycken + cache; alternativt byta till Hunspell-binär senare. |
| Lokala Ollama-modeller är svaga på svenska | Rekommendera modeller med bra svenska; prompt på svenska; modell väljs av användaren. |
| Hunspell hanterar svenska sammansättningar ofullständigt | Egen ordlista + ev. komplettering med Stava-liknande regler senare. |
| AI ”smiter” och skriver om text | Ingen skrivväg från AI till dokument; UI utan infoga-knapp; promptregler och tester. |
| Integritet – opublicerade texter till extern Ollama-server | Upplysning i gränssnittet när adressen inte är lokal. |

---

## 6. Beslut (besvarade frågor)

1. **Användare:** lokal enanvändarapp.
2. **AI:** Ollama, lokal eller extern.
3. **Redigering:** WYSIWYG-lik med möjlighet att växla till Markdown-vy.
4. **PDF-export:** nej, inte i v1.
5. **Versionshistorik:** ja, ingår i fas 1.
6. **Typsnitt:** ett typsnitt för hela dokumentet, valt som tema. Markdown är alltid originalet, även när man redigerar i WYSIWYG-vyn.
7. **Metadata:** lagras som YAML-frontmatter i början av Markdown-filen. Skydd finns sedan fas 2: frontmatter visas inte i Skriv-vyn, bevaras exakt vid sparning och räknas inte i ordräkning eller analys. En metadatapanel kommer senare, och Pandoc använder fälten vid export.

## 7. Status

- **Fas 0 – klar (2026-10-07):** repo-struktur, Dockerfile (Chainguard node → python → distroless python), docker-compose. Docker-imagen är ännu inte provbyggd.
- **Fas 1 – klar (2026-10-07):** dokument-API, autospar med konfliktskydd, papperskorg, versionshistorik (auto/manuell/namngiven, jämför, återställ), editor med Skriv/Markdown-växling, teman, typsnitt, fokus- och skrivmaskinsläge.
- **Fas 2 – klar (2026-10-07):**
  - Stavningskontroll med spylls och DSSO-ordlistan i Skriv-vyn, med egen ordlista och ignorera.
  - Synonymer från Synlex, inklusive grundform för böjda ord.
  - Högerklicksmeny för förslag och synonymer.
  - Analyspanel: LIX med skala, OVIX, statistik, ordfrekvens med markering i texten, längsta meningar och analys av markering. LIX visas i statusraden.
- **Tillägg till fas 2:** fraser i den egna ordlistan, till exempel "open source". De godkänns bara som helhet, och en svensk sammansättning efter bindestreck kontrolleras separat.
- **Kvar från fas 2:** nominalkvot (kräver ordklasstaggning). Optimering för mycket långa manus: Markdown serialiseras i dag vid varje paus i skrivandet, vilket märks först kring 50 000+ ord.
- **Fas 3 – klar (2026-10-07):**
  - Export till DOCX, ODT, RTF, HTML, MD och TXT med Pandoc 3.9 (bundlad via pypandoc_binary).
  - Mallarna Standard, Manus och Artikel för DOCX och ODT: A4, 2,5 cm marginaler, sidnummer.
  - A4 gäller alla exporter, även Standard (Pandocs egna mallar är i Letter-format), RTF och utskrift av HTML.
  - Frontmatter (title, author) blir dokumentegenskaper, språket sätts till sv-SE och citattecken lämnas orörda.
  - Import av DOCX, ODT, RTF, HTML, MD och TXT med Lua-filter som rensar bort sådant Markdown inte kan uttrycka. Import kan också ske genom att dra och släppa filer.
  - Imagen blir cirka 160 MB större av Pandoc-binären.
- **Fas 4 – klar (2026-10-07):**
  - AI-assistent via Ollama. Standard är `https://ollama.dglive.net` med `qwen3.6:35b`, och båda går att ändra med `WW_OLLAMA_URL` och `WW_OLLAMA_MODEL`.
  - Backend-proxy med strömning (NDJSON). AI-modulen saknar åtkomst till lagringen.
  - Svensk systemprompt som förbjuder omskrivning. Testat mot servern: modellen avböjer att skriva om och ger förslag med exakta citat.
  - Fem snabbval och fri chatt med följdfrågor. Markering avgör omfånget, och klickbara citat visar stället i texten.
  - Valbart resonemangsläge ("tänk efter"), modellval, stopp-knapp och upplysning om extern server.
  - Kontextstorlek (num_ctx) i steg om 16k, 32k och 64k. Texter längre än cirka 150 000 tecken kräver att man markerar ett avsnitt.
- **Modellval (2026-10-07):** på ollama.dglive.net finns bara en chattmodell, `qwen3.6:35b`. Den har ungefär 145 tokens/s och fungerar väl med resonemang på (cirka 25–35 s per granskning). Utan resonemang händer det att den hittar på språkfel, och svenskan har ibland stavfel. Att utvärdera: `gemma4:26b` eller `gemma4:31b`, som troligen är starkare på svenska.
- **Ej gjort i fas 4:** samtalen sparas inte mellan sessioner, utan ligger i minnet per dokument.
- **Nästa:** fas 5 – polering, tillgänglighet, prestanda för långa manus, säkerhet och release.
