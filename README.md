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
- **Allt är Markdown.** Endast formatering som Markdown kan uttrycka går att använda. Det finns inga typsnitt, färger eller understrykningar i själva texten. Klistrar du in formaterad text rensas sådant bort.
- **Typsnitt och tema** väljs under *Utseende* och gäller alltid hela texten. Du kan också ställa in storlek, radavstånd, textbredd, dimning av andra stycken och skrivmaskinsläge.
- **Autospar** sker strax efter att du slutat skriva.
- **Versioner:** ⌘S (Ctrl+S) sparar och lägger en version i historiken. Dessutom sparas en automatisk version högst var femte minut.
  - Under *Historik* kan du förhandsgranska en version, jämföra den med nuvarande text och återställa den.
  - En återställning sparar först den nuvarande texten, så inget går förlorat.
- **Borttagna dokument** flyttas till `data/.trash/` och kan återskapas därifrån.
- **Gränssnittet tonas bort** medan du skriver och kommer tillbaka när du rör musen.

| Kortkommando | Gör |
|---|---|
| ⌘S / Ctrl+S | Spara och skapa version |
| ⌘/ / Ctrl+/ | Växla Skriv/Markdown |
| ⌘O / Ctrl+O | Öppna dokumentlistan |
| Esc | Stäng paneler |

## Konfiguration

| Variabel | Standard | Beskrivning |
|---|---|---|
| `WW_DATA_PATH` | `./data` | Mapp på din dator för texterna (compose) |
| `WW_SNAPSHOT_MINUTES` | `5` | Minsta tid mellan automatiska versioner |
| `WW_OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama-instans för AI-stöd (fas 4) |
| `WW_OLLAMA_MODEL` | – | Förvald Ollama-modell (fas 4) |

## Utveckling

```sh
make setup          # Python-venv + npm-paket
make dev-backend    # API på :8080
make dev-frontend   # Vite på :5173 (proxar /api)
make test           # pytest + typkontroll/bygge av frontend
```

- **Backend:** Python, FastAPI (`backend/app`)
- **Frontend:** TypeScript, Vite, TipTap 3 med `@tiptap/markdown` (`frontend/src`)
- **API-dokumentation:** <http://localhost:8080/api/docs>

### Lagringsformat

```
data/
  Min text.md                       ← aktuellt dokument
  .history/Min text/index.json      ← versioner (metadata)
  .history/Min text/<tidsstämpel>.md
  .trash/                           ← borttagna dokument
```

## Licenser för typsnitt

Typsnitten Literata, Source Sans 3 och IBM Plex Mono är licensierade under SIL Open Font License 1.1 och levereras via Fontsource.
