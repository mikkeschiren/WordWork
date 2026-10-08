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
| Lagring | Filer i monterad volym `/data` (Markdown) + ögonblicksbilder i `/data/.history/`, AI-samtal i `/data/.chats/`, inställningar i `/data/.wordwork/` | Användaren äger sina filer, enkel backup, versionshistorik. |
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
- Säkerhet: port binds till `127.0.0.1`, Host-kontroll, CSP; image-skanning (Grype/Scout), SBOM (Syft).
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
- **Tillägg efter fas 4:**
  - AI stängs av automatiskt när Ollama-servern inte kan nås eller saknar chattmodell, och slås på igen när den svarar. Kontrollen har 3 s tidsgräns och cachas i 15–30 s. Resten av appen påverkas inte.
  - Den egna ordlistan kan redigeras: ändra en post direkt, sök, redigera hela listan som text. Ändringar som görs direkt i `ordlista.txt` läses in automatiskt.
- **Ej gjort i fas 4:** samtalen sparas inte mellan sessioner, utan ligger i minnet per dokument.
- **Fas 5 – klar (2026-10-07), version 1.0.0:**
  - "Utseende" har bytt namn till "Inställningar".
  - **Prestanda** (uppmätt med ett manus på 100 000 ord):
    - Markdown serialiseras först vid sparning, inte vid varje paus.
    - Statusraden använder snabbstatistik (cirka 40 ms i stället för 170 ms). En egen platshållare ersätter TipTaps, som gick igenom hela dokumentet vid varje tangenttryckning.
    - Stycken utanför skärmen hoppas över vid layout (`content-visibility`).
    - Resultat: inläsning 1,2 s → 0,7 s, tangenttryckning 31 → 20 ms (median, mätt till nästa bildruta), fördröjning efter paus 250 → cirka 85 ms. Hopp till en position i texten justeras efter rendering.
  - **Tillgänglighet:**
    - Kontrast för gråtext höjd till WCAG AA (minst 4,5:1) i alla teman.
    - Fokus flyttas in i paneler när de öppnas och tillbaka till texten när de stängs. `aria-expanded` och `aria-controls` på panelknappar.
    - Kortkommandolista med F1.
  - **Skrivmål** per dag (Inställningar). Framsteg visas i statusraden och summeras över dokument.
  - **Säkerhet:**
    - Host-kontroll mot DNS-rebinding (`WW_ALLOWED_HOSTS`).
    - Content-Security-Policy och säkerhetshuvuden.
    - Tydligt fel i stället för krasch om datamappen inte går att skriva i (`/api/health` och en banner i appen).
  - **Release:**
    - Version 1.0.0 syns i `/api/health` och i Inställningar, och imagen har OCI-etiketter.
    - README har avsnitt om säkerhet, säkerhetskopiering, uppdatering, felsökning och skanning/SBOM.
- **Version 1.1 (2026-10-07) – typografi:**
  - **Teckenpanel** (⌘.) med sök, tangentbordsstyrning och senast använda tecken.
  - **Automatiska ersättningar** via TipTap-inmatningsregler, där Backsteg ångrar. Citatstil ”…”, »…» eller raka. Gäller bara Skriv-vyn och aldrig kod.
  - **"Rätta typografin i texten"** med förhandsvisning per rad, och en version i historiken innan ändringen.
  - **"Infoga tecken …"** i högerklicksmenyn.
  - **Två rättningar på köpet:**
    - Tomma stycken sparas inte längre som `&nbsp;` i filen.
    - `content-visibility` från fas 5 kunde flytta markören vid mycket snabbt skrivande i nya stycken. Den gäller nu bara dokument med fler än 300 stycken och aldrig det aktuella stycket. Optimeringen slås på redan vid första renderingen, vilket också gav bättre siffror: inläsning cirka 0,6 s och tangenttryckning cirka 15 ms för 100 000 ord.
- **Version 1.1.1 (2026-10-07) – rättning av automatisk typografi:**
  - **Replikstreck:** `-- ` först i ett stycke blir `– `. Tidigare gjordes ingenting där, eftersom regeln för tankstreck undvek radbörjan (för `---`).
  - **Enter gav fel:** TipTap kör inmatningsreglerna även för Enter. Därför kunde `-- `, ` -` och `12-15` sluka radbrytningen. Reglerna matchar nu bara mellanslag, aldrig radbrytning.
- **Version 1.2.0 (2026-10-07) – inställningar och AI-samtal sparas:**
  - **Filer, inte SQLite.** Datamappen ligger ofta på värddatorn och synkas ibland via moln. SQLite är känsligt för låsning och korruption där, medan atomärt skrivna JSON-filer klarar sig. Det stämmer också med resten av appen: allt är läsbara filer, och säkerhetskopiering är att kopiera mappen. Lagringen ligger samlad i `storage.py`, så ett byte senare (till exempel för fritextsökning i samtal) rör bara den.
  - **Inställningar** i `.wordwork/settings.json` via `GET/PUT /api/settings`. Frontend äger formatet, och okända eller felaktiga värden ignoreras. Webbläsaren har en kopia för snabb start, utan att temat blinkar. Vid första start flyttas webbläsarens gamla inställningar (även AI-modell och *Tänk efter först*) till servern. Ändringar samlas i 0,4 s och sparas också om fliken stängs.
  - **AI-samtal** i `.chats/<dokument>/<id>.json` via `GET/PUT/DELETE /api/documents/{namn}/chats[/{id}]`. Det senaste samtalet öppnas automatiskt. Det finns en lista med tidigare samtal, *Nytt samtal* (ersätter *Rensa samtalet*) och *Ta bort* (till papperskorgen). Samtalen följer dokumentet vid namnbyte och borttagning. Servern tar bara emot kända fält och rollerna user/assistant, med högst 400 meddelanden och 4 MB per samtal.
  - **Kvar i webbläsaren:** senaste dokument, vy, senast använda tecken och dagens skrivmål.
- **Version 1.2.1 (2026-10-07) – gammal kod i öppen flik:**
  - **Orsak:** AI-samtal sparades inte, men inställningarna verkade sparas. En flik som var öppen när containern byggdes om körde fortfarande den gamla koden. Den sparade inställningar i webbläsaren, men inte samtal. Vid omladdning flyttades inställningarna till servern, men samtalen fanns bara i minnet.
  - **Rättning:** appen jämför sin version med serverns när fönstret får fokus och varje minut. Skiljer de sig visas *Word Work har uppdaterats … Ladda om*, och texten sparas före omladdningen. `index.html` skickas med `Cache-Control: no-cache`, så att en omladdning alltid hämtar den nya versionen.
- **Version 1.3.0 (2026-10-07) – grundfunktioner och säkrare lagring:**
  - **Sök och ersätt** (`search.ts`, `searchbar.ts`):
    - I Skriv-vyn används ett ProseMirror-tillägg som söker inom stycken och markerar alla träffar och den aktuella.
    - Vid ändringar flyttas gamla träffar och markeringar. Bara de ändrade styckena söks om. I ett manus på 100 000 ord med 2 865 träffar tar ett tangenttryck cirka 28 ms med sökningen öppen.
    - *Ersätt alla* är ett enda Ångra-steg.
    - I Markdown-vyn söks källtexten. Ersättningar görs med `execCommand("insertText")`, så att webbläsarens Ångra fungerar.
  - **Papperskorgen** (`GET /api/trash`, `POST /api/trash/{post}/restore`): dokument återställs med historik och AI-samtal. Upptagna namn får "(återställd)". Ett samtal kräver att dokumentet finns.
  - **Kopiera för publicering** (`publish.ts`): Markdown görs om till HTML med `marked` och rensas med DOMPurify, så att bara struktur blir kvar. Ren text läggs bredvid. Allt skrivs till urklipp med ClipboardItem, med `execCommand("copy")` som reserv.
  - **Servern sparar AI-svaren:** `/api/ai/chat` tar emot `document_name`, `chat_id` och `label`. I `finally` sparas fråga och svar, även när webbläsaren kopplar ner. Svaret får då etiketten "Avbrutet". Klienten skickar inte längre `PUT` för samtal.
  - **Lokal reservkopia** (`unsaved.ts`): misslyckas en sparning (nätverksfel eller 5xx) sparas texten i `localStorage` och skickas igen var femte sekund, vid fokus och vid `online`. Reservkopian skrivs också vid `beforeunload`. När dokumentet öppnas erbjuds en reservkopia som skiljer sig från serverns text tillbaka. Den gamla texten läggs då i historiken.
  - **Ladda ner allt** (`GET /api/backup`): hela datamappen som zip.
- **Version 1.4.0 (2026-10-07) – för kulturjournalister, ikoner:**
  - **Metadatapanel** (`frontmatter.ts`):
    - En egen minimal YAML-hantering för fält med ett värde per rad. Bara panelens fält skrivs om; kommentarer, listor och andra nycklar lämnas orörda. Värden citeras när YAML annars skulle tolka dem fel.
    - Längdmål och deadline visas i statusraden.
    - Exporten tar bort en rubrik först i texten som är identisk med `title`.
  - **Egna anteckningar** (`notes.ts`):
    - En TipTap-nod med egen Markdown-tokenizer för HTML-kommentarer på egen rad.
    - Anteckningarna tas bort ur statistik (`getPlainText`), *Kopiera för publicering* och alla exporter (`strip_notes` i `convert.py`, utom i kodblock).
  - **Citatlista och nominalstil** (`stats.ts`) i Analys-panelen.
    - En riktig nominalkvot kräver ordklasstaggning. Vi undersökte DSSO-ordlistans böjningsflaggor, men de skiljer inte ordklasser åt tillräckligt säkert. Därför räknas substantiveringar med snäva ändelsemönster, och det står tydligt i appen att det är en uppskattning.
  - **Långa meningar** (`longsentences.ts`): ett ProseMirror-tillägg som delar meningar som LIX-beräkningen. Vid ändringar räknas bara de ändrade styckena om. Gränsen sparas i inställningarna.
  - **Ikoner** (`icons.ts`): verktygsraden har bara egna linjeikoner (SVG, `currentColor`), med `aria-label` och `title` som visar namn och kortkommando.
  - **Rättning:** i sökningens stegvisa uppdatering missades stycken där text bara togs bort (`from === to`). Nu söks stycket om.
- **Version 1.4.1:** AI-knappen har en gem-ikon, en blinkning åt kontorsprogrammens gamla hjälpreda. Det är ett vanligt gem utan ansikte, och verktygstipset frågar om du vill ha hjälp.
- **Version 1.5.0 (2026-10-07) – ny sida före kapitel vid export:**
  - Val i exportdialogen (nej, nivå 1 eller nivå 2), som skickas som `chapters` till `/api/documents/{namn}/export`.
  - Lua-filtret `filters/chapters.lua` lägger en sidbrytning före varje rubrik på vald nivå, utom före den första om inget står före den.
  - Brytningen görs på olika sätt per format:
    - Word: ett 1 pt högt stycke med `w:br w:type="page"`.
    - OpenDocument: ett stycke med stilen `Pagebreak` (`break-after: page`), som nu finns i alla tre ODT-mallarna (`tools/make_templates.py`).
    - RTF: `\page`.
    - HTML: `break-after: page` vid utskrift.
  - Markdown och ren text påverkas inte.
  - Kontrollerat genom att konvertera till PDF med LibreOffice: varje kapitel börjar överst på en ny sida.
  - Manuella sidbrytningar, scenbrytningar och kapitelnavigering väntar (se samtalet om bokskrivande).
- **Version 1.6.0 (2026-10-08) – OpenAI-kompatibla AI-servrar:**
  - `WW_AI_API=openai` använder `ai_openai.py` (`/v1/models`, `/v1/chat/completions` med SSE) med samma gränssnitt som `OllamaClient`. Panelen, de sparade samtalen och regeln om att AI:n aldrig skriver i texten är oförändrade.
  - Nya variabler: `WW_AI_URL`, `WW_AI_MODEL`, `WW_AI_KEY` och `WW_AI_KEY_FILE`. `WW_OLLAMA_*` fungerar fortfarande. Nyckeln skickas som Bearer-huvud och finns aldrig i något API-svar.
  - Resonemang fångas från `reasoning_content`, `reasoning` och `<think>`-taggar. Taggar som delats mellan två strömmade bitar fångas också.
  - Avvisar servern `temperature` eller `stream_options` skickas frågan om utan dem.
  - `/api/ai/status` har nu fälten `api` och `think_control`. Panelen döljer *Tänk efter först* när det inte går att styra.
  - Testat mot en simulerad OpenAI-server (`tests/test_ai_openai.py`). En riktig server gick inte att nå från utvecklingsmiljön.
- **Version 1.6.1 (2026-10-08) – inställningar i .env:**
  - Standardvärdena är nu generiska: lokal Ollama (`http://host.docker.internal:11434` i Docker, `http://localhost:11434` utan) och ingen förvald modell, så att den första chattmodellen på servern används.
  - Våra egna värden (`ollama.dglive.net`, `qwen3.6:35b`) ligger i `.env`, som inte checkas in och inte kommer med i imagen (`.dockerignore`).
  - `.env.example` innehåller alla inställningar med standardvärden och förklaringar.
- **Version 1.7.0 (2026-10-08) – licens:**
  - Word Work har licensen Apache 2.0, Copyright 2026 Mikke Schirén. Det finns nu `LICENSE`, `NOTICE`, `THIRD_PARTY_LICENSES.md` och `LICENSES/` (texterna för GPL-2.0, GPL-3.0, LGPL-3.0 och MPL-2.0).
  - Imagen har `/app/licenses/` med `THIRD_PARTY_NOTICES.txt`, som skapas vid bygget med `frontend/scripts/notices.mjs` och `backend/tools/notices.py` utifrån de paket som faktiskt installerats. Imagen har också OCI-etiketterna `licenses=Apache-2.0` och `authors`.
  - Export-mallarna är omgjorda så att de inte bygger på Pandocs GPL-licensierade referensdokument. DOCX utgår från python-docx tomma dokument (MIT), och ODT byggs från grunden. Standardmallen är nu Cambria 12 p med rubriker i Calibri.
  - Kontrollerat genom att konvertera till PDF med LibreOffice: A4, sidnummer, kapitelbrytning, titel, författare, fotnoter och citat fungerar i alla tre mallarna och båda formaten.
  - Pandoc (GPL) körs som separat program. Den som sprider imagen ska låta licenstexten och källkodslänken följa med, och det gör de i `/app/licenses/`.
- **Kvar efter v1 (förslag):** utvärdering av gemma4 för bättre svenska, CI-arbetsflöde (`.github/` kunde inte skrivas härifrån).
