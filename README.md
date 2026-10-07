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
- **Typsnitt och tema** väljs under *Inställningar* och gäller alltid hela texten. Du kan också ställa in storlek, radavstånd, textbredd, dimning av andra stycken och skrivmaskinsläge.
- **Inställningarna sparas i datamappen** (`data/.wordwork/settings.json`), liksom valet av AI-modell. De följer därför med till en annan webbläsare och finns kvar efter en ominstallation. Bara vilken vy och vilket dokument som var öppet senast sparas i webbläsaren, liksom hur många ord du skrivit i dag.
- **Autospar** sker strax efter att du slutat skriva.
  - Svarar inte servern (till exempel medan containern startar om) visar statusraden *Inte sparat – försöker igen*. Texten sparas då i webbläsaren och skickas till servern så snart den svarar igen.
  - Stängs fliken innan texten hunnit sparas, erbjuds den osparade texten nästa gång du öppnar dokumentet. Du väljer *Återställ den* eller *Släng den*. Vid återställning läggs den tidigare texten i historiken.
- **Versioner:** ⌘S (Ctrl+S) sparar och lägger en version i historiken. Dessutom sparas en automatisk version högst var femte minut.
  - Under *Historik* kan du förhandsgranska en version, jämföra den med nuvarande text och återställa den.
  - En återställning sparar först den nuvarande texten, så inget går förlorat.
- **Borttagna dokument** flyttas till papperskorgen (`data/.trash/`) tillsammans med sin historik och sina AI-samtal.
  - Under *Dokument → Papperskorgen …* kan du återställa dokument och borttagna AI-samtal.
  - Är namnet upptaget får dokumentet namnet "… (återställd)".
  - Inget raderas på riktigt.
- **Sök och ersätt** (knappen *Sök*, ⌘F / Ctrl+F, eller ⌘⌥F / Ctrl+Alt+F för att börja i ersätt-fältet):
  - Alla träffar markeras.
  - Enter går till nästa träff och Shift+Enter till föregående. ⌘G (Ctrl+G) och F3 fungerar också när markören står i texten.
  - *Aa* skiljer på stora och små bokstäver, och *Hela ord* hittar bara hela ord.
  - *Ersätt* byter den aktuella träffen, och *Ersätt alla* byter alla i ett steg. Ett ⌘Z (Ctrl+Z) ångrar.
  - I Skriv-vyn söks den synliga texten, så Markdown-tecken som `**` påverkar inte. I Markdown-vyn söks källtexten, och träffen markeras där.
  - Esc stänger sökningen.
- **Kopiera för publicering** (⌘⇧C / Ctrl+Shift+C, eller *Exportera → Kopiera*):
  - Lägger texten i urklipp både som HTML och som ren text, med rubriker, fet och kursiv stil, citat, listor och länkar.
  - Texten kan klistras in direkt i WordPress eller ett annat publiceringssystem.
  - Frontmatter följer inte med. Huvudrubriken kan väljas bort, eftersom många publiceringssystem har ett eget rubrikfält.
- **Ladda ner allt** (*Dokument → Ladda ner allt (zip)*) ger hela datamappen som en zip-fil: dokument, versioner, AI-samtal, papperskorg och inställningar.
- **Gränssnittet tonas bort** medan du skriver och kommer tillbaka när du rör musen. Med tangentbordet når du knapparna med Tab.
- **Dagens skrivmål:** ställ in ett antal ord per dag under *Inställningar*. Statusraden visar hur många ord du skrivit i dag, i alla dokument.
- **Typografi:**
  - **Infoga tecken** (knappen *Tecken*, ⌘. / Ctrl+. eller högerklick → *Infoga tecken …*). Panelen har svenska citattecken, tankstreck, hårda och smala mellanslag, ellips, paragraftecken, bråk och bokstäver med accent. Sök på namn, till exempel "tankstreck" eller "grader". Piltangenterna flyttar, Enter infogar och stänger, och ett klick infogar och låter panelen vara öppen. Överst visas de senast använda tecknen.
  - **Automatiskt medan du skriver** (Skriv-vyn):
    - `"` blir ”
    - `'` blir ’
    - `--` blir tankstreck –
    - `---` blir långt tankstreck —
    - ` - ` blir ` – `
    - `-- ` först i ett stycke blir replikstreck `– ` (skönlitterär dialog). `- ` blir fortfarande punktlista och `---` avgränsningslinje.
    - `12-15` blir 12–15 (datum och telefonnummer lämnas orörda)
    - `...` blir …
    - `1/2` blir ½

    **Backsteg direkt efter ångrar** en ersättning. Under *Inställningar* kan du stänga av funktionen och välja citattecken: ”svenska”, »vinkel» eller raka. Kod och Markdown-vyn ändras aldrig.
  - **Rätta typografin i texten …** (längst ner i teckenpanelen) går igenom befintlig text, till exempel importerad text med raka citattecken. Ändringarna visas rad för rad innan de görs, och den tidigare texten sparas som en version i historiken. Kod, länkadresser och frontmatter lämnas orörda.
- **Stavningskontroll** (svensk Hunspell-ordlista) stryker under okända ord i Skriv-vyn.
  - Högerklicka på ett ord för rättningsförslag, *Lägg till i egen ordlista* eller *Ignorera*.
  - Den egna ordlistan sparas i `data/.wordwork/ordlista.txt`. Under *Inställningar → Egen ordlista* kan du lägga till, söka och ta bort poster, klicka på en post för att ändra den, eller redigera hela listan som text. Ändrar du filen direkt läses den in igen automatiskt.
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
  - **Samtalen sparas av servern** per dokument i `data/.chats/<dokument>/`. Fråga och svar sparas även om fliken stängs eller du trycker *Stoppa* mitt i ett svar. Svaret får då etiketten *Avbrutet*. När du öppnar panelen visas det senaste samtalet om texten. Tidigare samtal väljer du i listan ovanför samtalet. *Nytt samtal* börjar om, och det gamla finns kvar i listan. *Ta bort* flyttar samtalet till papperskorgen. Samtalen följer med när dokumentet byter namn och hamnar i papperskorgen med det.
  - Används en extern server står det i panelen, eftersom texten då lämnar datorn.
  - Går Ollama-servern inte att nå, eller saknar den chattmodell, fungerar allt annat som vanligt. AI-knappen döljs då och visas igen när servern svarar. Appen kontrollerar detta varje minut och när fönstret får fokus.

| Kortkommando | Gör |
|---|---|
| ⌘S / Ctrl+S | Spara och skapa version |
| ⌘/ / Ctrl+/ | Växla Skriv/Markdown |
| ⌘O / Ctrl+O | Öppna dokumentlistan |
| ⌘E / Ctrl+E | Exportera |
| ⌘F / Ctrl+F | Sök (⌘⌥F / Ctrl+Alt+F: sök och ersätt) |
| ⌘G / Ctrl+G, F3 | Nästa träff (med Shift: föregående) |
| ⌘⇧C / Ctrl+Shift+C | Kopiera för publicering |
| ⌘J / Ctrl+J | AI-assistent |
| ⌘. / Ctrl+. | Infoga tecken |
| F1 | Lista över kortkommandon |
| Esc | Stäng paneler |

## Konfiguration

| Variabel | Standard | Beskrivning |
|---|---|---|
| `WW_DATA_PATH` | `./data` | Mapp på din dator för texterna (compose) |
| `WW_SNAPSHOT_MINUTES` | `5` | Minsta tid mellan automatiska versioner |
| `WW_ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | Värdnamn som får användas för att nå appen. Lägg till t.ex. datorns namn om du når den på annat sätt. `*` stänger av kontrollen. |
| `WW_OLLAMA_URL` | `https://ollama.dglive.net` | Ollama-instans. Lokal Ollama: `http://host.docker.internal:11434`. Tom sträng (`WW_OLLAMA_URL=`) stänger av AI-stödet. |
| `WW_OLLAMA_MODEL` | `qwen3.6:35b` | Förvald modell (kan bytas i AI-panelen) |

## Drift

### Säkerhet
- Porten binds till `127.0.0.1`, så appen nås bara från den egna datorn.
- Appen godtar bara de värdnamn som står i `WW_ALLOWED_HOSTS`. Det skyddar mot DNS-rebinding, där en främmande webbplats försöker läsa dina texter via webbläsaren.
- Sidan skickas med en strikt Content-Security-Policy och andra säkerhetshuvuden. Den laddar ingenting utifrån.
- Containern körs som en användare utan root-rättigheter, på Chainguards minimala image utan skal.
- AI-frågor skickar texten till Ollama-servern i `WW_OLLAMA_URL`. Använd en lokal instans om texterna inte får lämna datorn.

### Säkerhetskopiering
Allt ligger i datamappen (`./data` eller `WW_DATA_PATH`):
- dokumenten som `.md`
- historiken i `.history/`
- papperskorgen i `.trash/`
- den egna ordlistan i `.wordwork/ordlista.txt`
- inställningarna i `.wordwork/settings.json`
- AI-samtalen i `.chats/`

Det enklaste är *Dokument → Ladda ner allt (zip)*. Du kan också kopiera mappen, till exempel med Time Machine, `rsync` eller en molnsynkad mapp, så har du allt. Det går bra att säkerhetskopiera medan appen körs, eftersom filer alltid skrivs helt innan de ersätts.

### Uppdatering
```sh
git pull
docker compose up -d --build
```
Datamappen påverkas inte av en uppdatering. Flikar som redan är öppna visar *Word Work har uppdaterats* med knappen *Ladda om*. Ladda om innan du fortsätter, eftersom den gamla koden annars körs vidare i fliken.

### Felsökning
- **Appen startar men visar "Kan inte skriva i datamappen".** Rättigheterna på mappen tillåter inte containerns användare att skriva. Kör `chmod 755 data`, eller `chmod -R u+rwX,go+rX data`, och starta om.
- **"Okänt värdnamn".** Du når appen via ett namn som inte står i `WW_ALLOWED_HOSTS`. Lägg till det.
- **Ingen AI-knapp.** Ollama-servern kan inte nås eller har ingen chattmodell. Se `curl http://localhost:8080/api/ai/status`.
- **Status och version:** `curl http://localhost:8080/api/health`.

### Skanning och SBOM
Imagen bygger på Chainguards images, som har få kända sårbarheter. Kontrollera själv med något av:
```sh
docker scout cves word-work:dev           # Docker Scout
grype word-work:dev                       # Anchore Grype
syft word-work:dev -o spdx-json > sbom.spdx.json   # SBOM
```

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
  .chats/Min text/<id>.json         ← AI-samtal om dokumentet
  .trash/                           ← borttagna dokument, historik och samtal
  .wordwork/settings.json           ← inställningar
  .wordwork/ordlista.txt            ← egen ordlista
```

Ett AI-samtal är en JSON-fil med `id`, `created`, `updated`, `model` och `messages`, där varje meddelande har `role` (`user` eller `assistant`), `content` och ibland `label` (snabbval), `thinking` (resonemang), `meta` och `error`. Inställningsfilen är ett JSON-objekt med samma nycklar som i appen. Okända eller felaktiga värden ignoreras och ersätts med standardvärden.

## Licenser

- **Typsnitt:** Literata, Source Sans 3 och IBM Plex Mono, SIL Open Font License 1.1, via Fontsource.
- **Stavningsordlista:** "Den stora svenska ordlistan" av Göran Andersson, GNU LGPL 3.0.
- **Synonymer:** Synlex (Folkets synonymlexikon) av Viggo Kann, KTH, i LibreOffice-konvertering.
- **Stavningsmotor:** spylls (MPL 2.0).
- **Konvertering:** Pandoc (GPL 2+), som körs som separat program via pypandoc_binary.

Se `backend/resources/sv/SOURCES.txt` för källor och licenstexter.
