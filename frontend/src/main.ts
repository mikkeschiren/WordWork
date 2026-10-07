import "@fontsource-variable/literata";
import "@fontsource-variable/literata/wght-italic.css";
import "@fontsource-variable/source-sans-3";
import "@fontsource-variable/source-sans-3/wght-italic.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/400-italic.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./style.css";

import { diffWords } from "diff";
import { api, ApiError, type Version } from "./api";
import { AIPanel } from "./ai";
import { closeMenu, openContextMenu } from "./contextmenu";
import { DocEditor, type ViewMode } from "./editor";
import { SpellService } from "./spell";
import { analyze, LIX_SCALE, lixLevel, type TextStats } from "./stats";
import {
  applySettings,
  FONTS,
  loadSettings,
  saveSettings,
  THEMES,
  type Font,
  type Settings,
  type Theme,
} from "./settings";
import { confirm, formatDate, h, isMod, modKey, prompt, showModal, toast } from "./ui";

const AUTOSAVE_MS = 1500;
const LAST_DOC_KEY = "ww.lastDoc";
const VIEW_KEY = "ww.view";

const KIND_LABEL: Record<Version["kind"], string> = {
  auto: "Automatisk",
  manual: "Sparad",
  named: "Namngiven",
  restore: "Återställd",
};

type SaveState = "saved" | "dirty" | "saving" | "error" | "conflict";

class App {
  private settings: Settings = loadSettings();
  private editor: DocEditor;
  private current: { name: string; modified: number } | null = null;
  private lastSaved = "";
  private saveState: SaveState = "saved";
  private saveTimer: number | undefined;
  private savePromise: Promise<void> | null = null;

  // DOM
  private titleBtn = h("button", { class: "doc-title", title: "Byt namn" });
  private viewBtns: Record<ViewMode, HTMLButtonElement>;
  private statusWords = h("span");
  private statusChars = h("span");
  private statusLix = h("button", { class: "status-lix", title: "Läsbarhet – öppna analys" });
  private statusSave = h("span", { class: "save-state" });
  private docsDrawer = h("aside", { class: "drawer left", "aria-label": "Dokument" });
  private historyDrawer = h("aside", { class: "drawer right", "aria-label": "Versionshistorik" });
  private analysisDrawer = h("aside", { class: "drawer right wide", "aria-label": "Textanalys" });
  private aiDrawer = h("aside", { class: "drawer right wide ai", "aria-label": "AI-assistent" });
  private aiButton = h("button", { hidden: true, title: `AI-assistent (${modKey}+J)` }, "AI");
  private ai: AIPanel;
  private spell = new SpellService();
  private highlighted: string | null = null;
  private includeStopwords = false;
  private analysisTimer: number | undefined;
  private settingsPanel = h("div", { class: "popover", role: "dialog", "aria-label": "Utseende" });
  private banner = h("div", { class: "banner", role: "alert", hidden: true });

  constructor(root: HTMLElement) {
    applySettings(this.settings);

    this.spell.enabled = this.settings.spellcheck;
    const host = h("div", { class: "editor-host" });
    this.editor = new DocEditor({
      host,
      spell: this.spell,
      onChange: (md) => this.onChange(md),
      onActivity: () => {
        document.body.classList.add("typing");
        closeMenu();
      },
      onSelection: () => {
        this.scheduleAnalysis();
        if (this.aiDrawer.classList.contains("open")) this.ai.updateScope();
      },
      onContextMenu: (event, view) =>
        openContextMenu(event, view, {
          spell: this.spell,
          replace: (from, to, text) => this.editor.replaceRange(from, to, text),
        }),
    });
    this.editor.typewriter = this.settings.typewriter;
    this.ai = new AIPanel({
      drawer: this.aiDrawer,
      closeButton: () => this.closeButton(),
      documentName: () => this.current?.name ?? null,
      documentText: () => this.editor.getMarkdown(),
      plainText: () => this.editor.getPlainText(),
      selectionText: () => this.editor.getSelectionText(),
      showInText: (phrase) => {
        if (this.editor.mode !== "write") this.setView("write", false);
        return this.editor.selectText(phrase);
      },
      flush: () => this.flush(),
    });
    this.aiButton.addEventListener("click", () => this.toggleDrawer(this.aiDrawer));

    const viewBtn = (mode: ViewMode, label: string) =>
      h(
        "button",
        {
          class: "seg",
          "aria-pressed": "false",
          title: `${label} (${modKey}+/ växlar)`,
          onclick: () => this.setView(mode),
        },
        label,
      );
    this.viewBtns = { write: viewBtn("write", "Skriv"), markdown: viewBtn("markdown", "Markdown") };

    const topbar = h(
      "header",
      { class: "chrome topbar" },
      h(
        "div",
        { class: "group" },
        h(
          "button",
          { onclick: () => this.toggleDrawer(this.docsDrawer), title: `Dokument (${modKey}+O)` },
          "Dokument",
        ),
        h("button", { onclick: () => this.newDocument(), title: "Nytt dokument" }, "Nytt"),
        h("button", { onclick: () => this.showExport(), title: `Exportera (${modKey}+E)` }, "Exportera"),
      ),
      this.titleBtn,
      h(
        "div",
        { class: "group" },
        h("div", { class: "segmented", role: "group", "aria-label": "Vy" }, ...Object.values(this.viewBtns)),
        h("button", { onclick: () => this.toggleDrawer(this.analysisDrawer) }, "Analys"),
        this.aiButton,
        h("button", { onclick: () => this.toggleDrawer(this.historyDrawer) }, "Historik"),
        h("button", { onclick: (e: Event) => this.toggleSettings(e) }, "Utseende"),
        h("button", { onclick: () => this.toggleFullscreen(), title: "Helskärm" }, "Helskärm"),
      ),
    );
    this.titleBtn.addEventListener("click", () => this.renameCurrent());
    this.statusLix.addEventListener("click", () => this.toggleDrawer(this.analysisDrawer));

    const statusbar = h(
      "footer",
      { class: "chrome statusbar" },
      this.statusWords,
      this.statusChars,
      this.statusLix,
      this.statusSave,
    );

    root.append(
      topbar,
      this.banner,
      h("main", { class: "page" }, host),
      statusbar,
      this.docsDrawer,
      this.historyDrawer,
      this.analysisDrawer,
      this.aiDrawer,
      this.settingsPanel,
    );

    this.bindGlobalEvents();
    this.bindDropImport();
    this.setView((localStorage.getItem(VIEW_KEY) as ViewMode) || "write", false);
  }

  // ---------------- uppstart ----------------
  async start(): Promise<void> {
    void this.spell.loadDictionary();
    void this.ai.init().then((enabled) => (this.aiButton.hidden = !enabled));
    const docs = await api.list();
    let name = localStorage.getItem(LAST_DOC_KEY);
    if (!name || !docs.some((d) => d.name === name)) name = docs[0]?.name ?? null;
    if (!name) name = (await api.create()).name;
    await this.open(name);
  }

  // ---------------- dokument ----------------
  async open(name: string): Promise<void> {
    await this.flush();
    const doc = await api.get(name);
    if (this.current?.name !== doc.name) this.ai?.reset();
    this.current = { name: doc.name, modified: doc.modified };
    this.lastSaved = doc.content;
    this.editor.load(doc.content);
    this.setSaveState("saved");
    this.updateTitle();
    this.updateStats(doc.content);
    this.hideBanner();
    try {
      localStorage.setItem(LAST_DOC_KEY, doc.name);
    } catch {
      /* ignorera */
    }
    this.editor.focus();
  }

  private async newDocument(): Promise<void> {
    const name = await prompt("Nytt dokument", "", "Skapa");
    if (name === null) return;
    try {
      const doc = await api.create(name);
      await this.open(doc.name);
      this.closeDrawers();
    } catch (e) {
      toast(errorText(e));
    }
  }

  private async renameCurrent(): Promise<void> {
    if (!this.current) return;
    const name = await prompt("Byt namn", this.current.name, "Byt namn");
    if (!name || name === this.current.name) return;
    await this.flush();
    try {
      const doc = await api.rename(this.current.name, name);
      this.current = { name: doc.name, modified: doc.modified };
      localStorage.setItem(LAST_DOC_KEY, doc.name);
      this.updateTitle();
      if (this.docsDrawer.classList.contains("open")) this.renderDocs();
    } catch (e) {
      toast(errorText(e));
    }
  }

  private async deleteDocument(name: string): Promise<void> {
    const ok = await confirm(
      "Ta bort dokument",
      `”${name}” flyttas till papperskorgen i datamappen (.trash) och kan återskapas därifrån.`,
      "Ta bort",
      true,
    );
    if (!ok) return;
    if (this.current?.name === name) await this.flush();
    await api.remove(name);
    if (this.current?.name === name) {
      this.current = null;
      await this.start();
    }
    this.renderDocs();
  }

  // ---------------- sparning ----------------
  private onChange(md: string): void {
    this.updateStats(md);
    if (!this.current || this.saveState === "conflict") return;
    if (md === this.lastSaved) {
      if (this.saveState === "dirty") this.setSaveState("saved");
      return;
    }
    this.setSaveState("dirty");
    window.clearTimeout(this.saveTimer);
    this.saveTimer = window.setTimeout(() => void this.save(), AUTOSAVE_MS);
  }

  private async save(snapshot = false, force = false): Promise<void> {
    if (!this.current) return;
    if (this.savePromise) await this.savePromise;
    window.clearTimeout(this.saveTimer);
    const content = this.editor.getMarkdown();
    if (content === this.lastSaved && !snapshot) {
      if (this.saveState !== "conflict") this.setSaveState("saved");
      return;
    }
    const cur = this.current;
    this.setSaveState("saving");
    this.savePromise = (async () => {
      try {
        const r = await api.save(cur.name, content, force ? null : cur.modified, snapshot);
        cur.modified = r.modified;
        this.lastSaved = content;
        this.setSaveState(this.editor.getMarkdown() === content ? "saved" : "dirty");
        if (snapshot) toast("Sparat – en version har lagts i historiken");
        if (this.historyDrawer.classList.contains("open")) void this.renderHistory();
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          this.setSaveState("conflict");
          this.showConflict();
        } else {
          this.setSaveState("error");
          toast(`Kunde inte spara: ${errorText(e)}`);
        }
      } finally {
        this.savePromise = null;
      }
    })();
    await this.savePromise;
  }

  /** Spara direkt om något är osparat (inför byte av dokument m.m.). */
  private async flush(): Promise<void> {
    if (!this.current) return;
    if (this.saveState === "dirty" || this.saveState === "saving") await this.save();
  }

  private setSaveState(state: SaveState): void {
    this.saveState = state;
    const text: Record<SaveState, string> = {
      saved: "Sparat",
      dirty: "Osparade ändringar",
      saving: "Sparar …",
      error: "Fel vid sparning",
      conflict: "Konflikt",
    };
    this.statusSave.textContent = text[state];
    this.statusSave.dataset.state = state;
  }

  private showConflict(): void {
    this.banner.replaceChildren(
      h("span", {}, "Dokumentet har ändrats någon annanstans, t.ex. i en annan flik."),
      h(
        "button",
        {
          onclick: async () => {
            if (this.current) await this.open(this.current.name);
          },
        },
        "Ladda om (mina senaste ändringar kastas)",
      ),
      h(
        "button",
        {
          class: "primary",
          onclick: async () => {
            this.hideBanner();
            this.setSaveState("dirty");
            await this.save(true, true);
          },
        },
        "Behåll min version",
      ),
    );
    this.banner.hidden = false;
  }

  private hideBanner(): void {
    this.banner.hidden = true;
  }

  // ---------------- vy & statistik ----------------
  private setView(mode: ViewMode, focus = true): void {
    this.editor.setMode(mode);
    for (const [m, btn] of Object.entries(this.viewBtns)) {
      btn.setAttribute("aria-pressed", String(m === mode));
    }
    try {
      localStorage.setItem(VIEW_KEY, mode);
    } catch {
      /* ignorera */
    }
    if (focus) this.editor.focus();
  }

  private updateTitle(): void {
    const name = this.current?.name ?? "";
    this.titleBtn.textContent = name;
    document.title = name ? `${name} – Word Work` : "Word Work";
  }

  private updateStats(_md?: string): void {
    const stats = analyze(this.editor.getPlainText(), { top: 0 });
    this.statusWords.textContent = `${stats.words.toLocaleString("sv-SE")} ord`;
    this.statusChars.textContent = `${stats.chars.toLocaleString("sv-SE")} tecken`;
    this.statusLix.textContent = stats.lix === null ? "LIX –" : `LIX ${Math.round(stats.lix)}`;
    this.statusLix.title =
      stats.lix === null ? "Läsbarhet" : `Läsbarhet: ${lixLevel(stats.lix).label.toLowerCase()} – öppna analys`;
    this.scheduleAnalysis();
  }

  // ---------------- lådor & paneler ----------------
  private toggleDrawer(drawer: HTMLElement): void {
    const open = !drawer.classList.contains("open");
    this.closeDrawers();
    if (open) {
      drawer.classList.add("open");
      document.body.dataset.drawer = drawer.classList.contains("left") ? "left" : "right";
      if (drawer === this.docsDrawer) void this.renderDocs();
      else if (drawer === this.analysisDrawer) this.renderAnalysis();
      else if (drawer === this.aiDrawer) void this.ai.render().then(() => this.ai.focusInput());
      else void this.renderHistory();
    } else {
      this.editor.focus();
    }
  }

  private closeDrawers(): void {
    delete document.body.dataset.drawer;
    this.docsDrawer.classList.remove("open");
    this.historyDrawer.classList.remove("open");
    this.aiDrawer.classList.remove("open");
    this.settingsPanel.classList.remove("open");
    if (this.analysisDrawer.classList.contains("open")) {
      this.analysisDrawer.classList.remove("open");
      this.setHighlight(null);
    }
  }

  private async renderDocs(): Promise<void> {
    await this.flush();
    const docs = await api.list();
    const list = h("ul", { class: "list" });
    for (const d of docs) {
      const active = d.name === this.current?.name;
      list.append(
        h(
          "li",
          { class: active ? "active" : "" },
          h(
            "button",
            {
              class: "item",
              onclick: async () => {
                await this.open(d.name);
                this.closeDrawers();
              },
            },
            h("span", { class: "name" }, d.name),
            h(
              "span",
              { class: "meta" },
              `${d.words.toLocaleString("sv-SE")} ord · ${formatDate(new Date(d.modified * 1000))}`,
            ),
          ),
          h(
            "button",
            {
              class: "icon",
              title: `Ta bort ”${d.name}”`,
              "aria-label": `Ta bort ${d.name}`,
              onclick: () => this.deleteDocument(d.name),
            },
            "×",
          ),
        ),
      );
    }
    this.docsDrawer.replaceChildren(
      h(
        "div",
        { class: "drawer-head" },
        this.closeButton(),
        h("h2", {}, "Dokument"),
        h("button", { onclick: () => this.chooseImport(), title: "Importera DOCX, ODT, RTF, HTML, Markdown eller text" }, "Importera …"),
        h("button", { onclick: () => this.newDocument() }, "Nytt"),
      ),
      list,
      h("p", { class: "meta hint-drop" }, "Du kan också släppa filer var som helst i fönstret för att importera dem."),
    );
  }

  private async renderHistory(): Promise<void> {
    if (!this.current) return;
    const name = this.current.name;
    await this.flush();
    const versions = await api.history(name);
    const list = h("ul", { class: "list" });
    if (!versions.length) {
      list.append(
        h("li", { class: "empty" }, `Inga versioner ännu. Tryck ${modKey}+S för att spara en.`),
      );
    }
    for (const v of versions) {
      list.append(
        h(
          "li",
          {},
          h(
            "button",
            { class: "item", onclick: () => this.previewVersion(name, v) },
            h("span", { class: "name" }, v.label || formatDate(new Date(v.created))),
            h(
              "span",
              { class: "meta" },
              `${v.label ? formatDate(new Date(v.created)) + " · " : ""}${KIND_LABEL[v.kind]} · ${v.words.toLocaleString("sv-SE")} ord`,
            ),
          ),
        ),
      );
    }
    this.historyDrawer.replaceChildren(
      h(
        "div",
        { class: "drawer-head" },
        this.closeButton(),
        h("h2", {}, "Historik"),
        h(
          "button",
          {
            onclick: async () => {
              const label = await prompt("Spara namngiven version", "", "Spara");
              if (label === null) return;
              await this.save();
              await api.snapshot(name, label);
              toast(`Versionen ”${label}” är sparad`);
              void this.renderHistory();
            },
          },
          "Spara version …",
        ),
      ),
      list,
    );
  }

  private async previewVersion(name: string, v: Version): Promise<void> {
    const { content } = await api.version(name, v.id);
    const current = this.editor.getMarkdown();
    let showDiff = false;
    const body = h("div", { class: "preview" });
    const render = () => {
      body.replaceChildren();
      if (!showDiff) {
        body.textContent = content;
        return;
      }
      // Grön = finns i nuvarande text men inte i versionen; röd = finns bara i versionen.
      for (const part of diffWords(content, current)) {
        const tag = part.added ? "ins" : part.removed ? "del" : "span";
        body.append(h(tag, {}, part.value));
      }
    };
    render();
    await showModal((close) => {
      const diffBtn = h(
        "button",
        {
          onclick: () => {
            showDiff = !showDiff;
            diffBtn.textContent = showDiff ? "Visa versionen" : "Jämför med nuvarande";
            render();
          },
        },
        "Jämför med nuvarande",
      );
      return h(
        "div",
        { class: "version-modal" },
        h("h2", {}, v.label || formatDate(new Date(v.created))),
        h(
          "p",
          { class: "meta" },
          `${formatDate(new Date(v.created))} · ${KIND_LABEL[v.kind]} · ${v.words.toLocaleString("sv-SE")} ord`,
        ),
        body,
        h(
          "div",
          { class: "actions" },
          diffBtn,
          h("span", { class: "spacer" }),
          h("button", { onclick: close }, "Stäng"),
          h(
            "button",
            {
              class: "primary",
              onclick: async () => {
                await this.save();
                const r = await api.restore(name, v.id);
                if (this.current?.name === name) {
                  this.current.modified = r.modified;
                  this.lastSaved = r.content;
                  this.editor.load(r.content);
                  this.updateStats(r.content);
                  this.setSaveState("saved");
                }
                close();
                toast("Versionen är återställd. Den tidigare texten finns kvar i historiken.");
                void this.renderHistory();
              },
            },
            "Återställ den här versionen",
          ),
        ),
      );
    });
  }

  // ---------------- analys ----------------
  private scheduleAnalysis(): void {
    if (!this.analysisDrawer.classList.contains("open")) return;
    window.clearTimeout(this.analysisTimer);
    this.analysisTimer = window.setTimeout(() => this.renderAnalysis(), 300);
  }

  private setHighlight(word: string | null): void {
    this.highlighted = word;
    if (word && this.editor.mode !== "write") this.setView("write", false);
    this.editor.highlight(word);
  }

  private renderAnalysis(): void {
    // En markering räknas först när den är minst några ord (inte bara ett markerat ord).
    const sel = this.editor.getSelectionText();
    const selection = (sel.match(/\S+/g)?.length ?? 0) >= 3 ? sel : "";
    const text = selection || this.editor.getPlainText();
    const st: TextStats = analyze(text, { includeStopwords: this.includeStopwords, top: 40 });
    const nf = (n: number, d = 0) =>
      n.toLocaleString("sv-SE", { minimumFractionDigits: d, maximumFractionDigits: d });

    const row = (label: string, value: string, hint = "") =>
      h("div", { class: "stat", title: hint }, h("span", {}, label), h("strong", {}, value));

    // LIX-mätare
    let lixBlock: HTMLElement;
    if (st.lix === null) {
      lixBlock = h("p", { class: "meta" }, "Skriv några meningar så räknas LIX ut.");
    } else {
      const level = lixLevel(st.lix);
      const pct = Math.min(100, Math.max(0, ((st.lix - 15) / (70 - 15)) * 100));
      lixBlock = h(
        "div",
        { class: "lix" },
        h(
          "div",
          { class: "lix-head" },
          h("span", { class: "lix-value" }, nf(st.lix)),
          h("span", {}, h("strong", {}, level.label), h("br", {}), h("span", { class: "meta" }, level.example)),
        ),
        h(
          "div",
          { class: "lix-scale", role: "img", "aria-label": `LIX ${nf(st.lix)} – ${level.label}` },
          ...LIX_SCALE.map((l) => h("span", { class: l === level ? "on" : "" })),
          h("i", { style: `left:${pct}%` }),
        ),
        h(
          "div",
          { class: "lix-labels" },
          ...["25", "30", "40", "50", "60"].map((t) => h("span", {}, t)),
        ),
      );
    }

    const freqList = h("ol", { class: "freq" });
    const maxCount = st.frequency[0]?.count ?? 1;
    for (const f of st.frequency) {
      const active = this.highlighted === f.word;
      freqList.append(
        h(
          "li",
          {},
          h(
            "button",
            {
              class: active ? "active" : "",
              title: active ? "Ta bort markering" : "Markera i texten",
              onclick: () => {
                this.setHighlight(active ? null : f.word);
                this.renderAnalysis();
              },
            },
            h("span", { class: "bar", style: `width:${(f.count / maxCount) * 100}%` }),
            h("span", { class: "w" }, f.word),
            h("span", { class: "c" }, String(f.count)),
          ),
        ),
      );
    }

    const sentenceList = h("ol", { class: "sentences" });
    for (const s of st.longestSentences) {
      sentenceList.append(
        h(
          "li",
          {},
          h(
            "button",
            {
              title: "Visa i texten",
              onclick: () => {
                if (this.editor.mode !== "write") this.setView("write", false);
                this.editor.selectText(s.text);
              },
            },
            h("span", { class: "c" }, `${s.words} ord`),
            h("span", { class: "t" }, s.text.length > 140 ? `${s.text.slice(0, 140)} …` : s.text),
          ),
        ),
      );
    }

    const stopToggle = h(
      "label",
      { class: "check small" },
      h("input", {
        type: "checkbox",
        checked: this.includeStopwords,
        onchange: (e: Event) => {
          this.includeStopwords = (e.target as HTMLInputElement).checked;
          this.renderAnalysis();
        },
      }),
      h("span", {}, "Visa småord"),
    );

    const scrollTop = this.analysisDrawer.scrollTop;
    this.analysisDrawer.replaceChildren(
      h(
        "div",
        { class: "drawer-head" },
        this.closeButton(),
        h("h2", {}, "Analys"),
        h("span", { class: "meta scope" }, selection ? "Markerad text" : "Hela texten"),
      ),
      h("section", {}, h("h3", {}, "Läsbarhet (LIX)"), lixBlock),
      h(
        "section",
        { class: "grid" },
        row("Ord", nf(st.words)),
        row("Unika ord", nf(st.uniqueWords)),
        row("Meningar", nf(st.sentences)),
        row("Stycken", nf(st.paragraphs)),
        row("Tecken", nf(st.chars)),
        row("Utan blanksteg", nf(st.charsNoSpaces)),
        row("Ord per mening", nf(st.avgSentenceLength, 1)),
        row("Bokstäver per ord", nf(st.avgWordLength, 1)),
        row("Långa ord", st.words ? `${nf((st.longWords / st.words) * 100)} %` : "–", "Ord med fler än sex bokstäver"),
        row(
          "OVIX",
          st.ovix === null ? "–" : nf(st.ovix, 0),
          "Ordvariationsindex – högre värde betyder mer varierat ordförråd",
        ),
        row("Lästid", st.readingMinutes < 1 ? "< 1 min" : `${nf(Math.round(st.readingMinutes))} min`),
      ),
      h(
        "section",
        {},
        h("div", { class: "section-head" }, h("h3", {}, "Vanligaste orden"), stopToggle),
        st.frequency.length ? freqList : h("p", { class: "meta" }, "Inga ord ännu."),
        h("p", { class: "meta" }, "Klicka på ett ord för att markera alla förekomster i texten."),
      ),
      h(
        "section",
        {},
        h("h3", {}, "Längsta meningarna"),
        st.longestSentences.length ? sentenceList : h("p", { class: "meta" }, "Inga meningar ännu."),
      ),
    );
    this.analysisDrawer.scrollTop = scrollTop;
  }

  private closeButton(): HTMLElement {
    return h(
      "button",
      {
        class: "icon close",
        title: "Stäng (Esc)",
        "aria-label": "Stäng",
        onclick: () => {
          this.closeDrawers();
          this.editor.focus();
        },
      },
      "×",
    );
  }

  private async showDictionary(): Promise<void> {
    this.closeDrawers();
    const { words } = await api.dictionary();
    await showModal((close) => {
      const list = h("ul", { class: "list dict" });
      const render = (ws: string[]) => {
        list.replaceChildren(
          ...(ws.length
            ? ws.map((w) =>
                h(
                  "li",
                  {},
                  h("span", { class: "item" }, w, w.includes(" ") ? h("span", { class: "tag" }, "fras") : null),
                  h(
                    "button",
                    {
                      class: "icon",
                      title: `Ta bort ”${w}”`,
                      "aria-label": `Ta bort ${w}`,
                      onclick: async () => {
                        const r = await api.dictionaryRemove(w);
                        this.spell.forget(w, r.words);
                        render(r.words);
                      },
                    },
                    "×",
                  ),
                ),
              )
            : [h("li", { class: "empty" }, "Ordlistan är tom. Högerklicka på ett understruket ord – eller markera flera ord – för att lägga till.")]),
        );
      };
      render(words);
      const input = h("input", {
        type: "text",
        placeholder: "Nytt ord eller fras, t.ex. open source",
        "aria-label": "Nytt ord eller fras",
      }) as HTMLInputElement;
      const form = h(
        "form",
        { class: "dict-add" },
        input,
        h("button", { type: "submit" }, "Lägg till"),
      );
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const entry = input.value.trim().split(/\s+/).join(" ");
        if (!entry) return;
        try {
          await this.spell.addToDictionary(entry);
          input.value = "";
          render((await api.dictionary()).words);
        } catch (err) {
          toast(errorText(err));
        }
      });
      return h(
        "div",
        {},
        h("h2", {}, "Egen ordlista"),
        h(
          "p",
          { class: "meta" },
          "Ord här godkänns av stavningskontrollen. En fras (t.ex. ”open source”) godkänns bara när orden står tillsammans – ”open” ensamt räknas fortfarande som stavfel. Listan sparas i datamappen (.wordwork/ordlista.txt).",
        ),
        form,
        list,
        h("div", { class: "actions" }, h("button", { class: "primary", onclick: close }, "Klar")),
      );
    });
  }

  // ---------------- import & export ----------------
  private async showExport(): Promise<void> {
    if (!this.current) return;
    this.closeDrawers();
    await this.flush();
    const name = this.current.name;
    let opts;
    try {
      opts = await api.exportOptions();
    } catch (e) {
      toast(errorText(e));
      return;
    }
    const remembered = (key: string, fallback: string) => {
      try {
        return localStorage.getItem(key) ?? fallback;
      } catch {
        return fallback;
      }
    };
    let format = remembered("ww.exportFormat", "docx");
    let template = remembered("ww.exportTemplate", "standard");
    if (!opts.formats.some((f) => f.key === format)) format = opts.formats[0].key;

    await showModal((close) => {
      const tplSelect = h("select", {
        "aria-label": "Mall",
        onchange: (e: Event) => (template = (e.target as HTMLSelectElement).value),
      });
      for (const t of opts.templates) {
        tplSelect.append(h("option", { value: t.key, selected: t.key === template }, t.label));
      }
      const tplRow = h("label", { class: "field" }, h("span", {}, "Mall"), tplSelect);
      const updateTpl = () => {
        const f = opts.formats.find((x) => x.key === format);
        tplSelect.disabled = !f?.templates;
        tplRow.classList.toggle("disabled", !f?.templates);
      };
      const radios = h(
        "div",
        { class: "radio-list", role: "radiogroup", "aria-label": "Format" },
        ...opts.formats.map((f) =>
          h(
            "label",
            {},
            h("input", {
              type: "radio",
              name: "export-format",
              value: f.key,
              checked: f.key === format,
              onchange: () => {
                format = f.key;
                updateTpl();
              },
            }),
            h("span", {}, f.label),
          ),
        ),
      );
      updateTpl();
      return h(
        "div",
        { class: "export-modal" },
        h("h2", {}, `Exportera ”${name}”`),
        radios,
        tplRow,
        h("p", { class: "meta" }, "Mallen gäller Word och OpenDocument. Titel och författare i frontmatter (title, author) följer med som dokumentegenskaper."),
        h(
          "div",
          { class: "actions" },
          h("button", { onclick: close }, "Avbryt"),
          h(
            "button",
            {
              class: "primary",
              onclick: () => {
                try {
                  localStorage.setItem("ww.exportFormat", format);
                  localStorage.setItem("ww.exportTemplate", template);
                } catch {
                  /* ignorera */
                }
                const tpl = opts.formats.find((x) => x.key === format)?.templates ? template : "standard";
                void this.download(api.exportUrl(name, format, tpl));
                close();
              },
            },
            "Ladda ner",
          ),
        ),
      );
    });
  }

  private async download(url: string): Promise<void> {
    // Hämta först, så att fel kan visas i stället för en trasig nedladdning.
    try {
      const res = await fetch(url);
      if (!res.ok) {
        let msg = res.statusText;
        try {
          msg = (await res.json()).detail ?? msg;
        } catch {
          /* inget JSON */
        }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") ?? "";
      const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
      const filename = m ? decodeURIComponent(m[1]) : "dokument";
      const a = h("a", { href: URL.createObjectURL(blob), download: filename });
      document.body.append(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
      toast(`Exporterade ${filename}`);
    } catch (e) {
      toast(`Kunde inte exportera: ${errorText(e)}`);
    }
  }

  private chooseImport(): void {
    const input = h("input", {
      type: "file",
      multiple: true,
      accept: ".docx,.odt,.rtf,.html,.htm,.md,.markdown,.txt",
    }) as HTMLInputElement;
    input.addEventListener("change", () => void this.importFiles([...(input.files ?? [])]));
    input.click();
  }

  private async importFiles(files: File[]): Promise<void> {
    let last: string | null = null;
    for (const file of files) {
      try {
        toast(`Importerar ${file.name} …`);
        const doc = await api.importFile(file);
        last = doc.name;
      } catch (e) {
        toast(`${file.name}: ${errorText(e)}`);
      }
    }
    if (last) {
      await this.open(last);
      this.closeDrawers();
      toast(files.length > 1 ? `${files.length} filer importerade` : `Importerade ”${last}”`);
    }
  }

  private bindDropImport(): void {
    const overlay = h("div", { class: "drop-overlay", hidden: true }, h("div", {}, "Släpp för att importera"));
    document.body.append(overlay);
    let depth = 0;
    const hasFiles = (e: DragEvent) => [...(e.dataTransfer?.types ?? [])].includes("Files");
    window.addEventListener("dragenter", (e) => {
      if (!hasFiles(e)) return;
      depth++;
      overlay.hidden = false;
    });
    window.addEventListener("dragleave", (e) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) overlay.hidden = true;
    });
    window.addEventListener("dragover", (e) => {
      if (hasFiles(e)) e.preventDefault();
    });
    window.addEventListener("drop", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      overlay.hidden = true;
      void this.importFiles([...(e.dataTransfer?.files ?? [])]);
    });
  }

  private toggleSettings(e?: Event): void {
    e?.stopPropagation();
    const open = !this.settingsPanel.classList.contains("open");
    this.closeDrawers();
    if (!open) return;
    this.renderSettings();
    this.settingsPanel.classList.add("open");
  }

  private renderSettings(): void {
    const s = this.settings;
    const update = (patch: Partial<Settings>) => {
      Object.assign(s, patch);
      applySettings(s);
      saveSettings(s);
      this.editor.typewriter = s.typewriter;
      if (this.spell.enabled !== s.spellcheck) {
        this.spell.enabled = s.spellcheck;
        this.spell.changed();
      }
    };
    const select = <T extends string>(
      label: string,
      value: T,
      options: Record<T, string>,
      onchange: (v: T) => void,
    ) => {
      const sel = h("select", {
        onchange: (e: Event) => onchange((e.target as HTMLSelectElement).value as T),
      });
      for (const [k, text] of Object.entries(options) as [T, string][]) {
        sel.append(h("option", { value: k, selected: k === value }, text));
      }
      return h("label", {}, h("span", {}, label), sel);
    };
    const range = (
      label: string,
      value: number,
      min: number,
      max: number,
      step: number,
      fmt: (v: number) => string,
      onchange: (v: number) => void,
    ) => {
      const out = h("output", {}, fmt(value));
      const input = h("input", {
        type: "range",
        min,
        max,
        step,
        value,
        oninput: (e: Event) => {
          const v = Number((e.target as HTMLInputElement).value);
          out.textContent = fmt(v);
          onchange(v);
        },
      });
      return h("label", {}, h("span", {}, label), input, out);
    };
    const check = (label: string, value: boolean, onchange: (v: boolean) => void) =>
      h(
        "label",
        { class: "check" },
        h("input", {
          type: "checkbox",
          checked: value,
          onchange: (e: Event) => onchange((e.target as HTMLInputElement).checked),
        }),
        h("span", {}, label),
      );

    const fontLabels = Object.fromEntries(
      Object.entries(FONTS).map(([k, v]) => [k, v.label]),
    ) as Record<Font, string>;

    this.settingsPanel.replaceChildren(
      h("h2", {}, "Utseende"),
      h("p", { class: "hint" }, "Typsnittet gäller hela texten. Själva dokumentet är alltid ren Markdown."),
      select<Theme>("Tema", s.theme, THEMES, (v) => update({ theme: v })),
      select<Font>("Typsnitt", s.font, fontLabels, (v) => update({ font: v })),
      range("Storlek", s.size, 14, 30, 1, (v) => `${v} px`, (v) => update({ size: v })),
      range("Radavstånd", s.lineHeight, 1.3, 2.2, 0.05, (v) => v.toFixed(2), (v) => update({ lineHeight: v })),
      range("Textbredd", s.width, 40, 100, 2, (v) => `${v} tecken`, (v) => update({ width: v })),
      check("Dimma andra stycken än det jag skriver i", s.focusParagraph, (v) => update({ focusParagraph: v })),
      check("Skrivmaskinsläge (aktuell rad i mitten)", s.typewriter, (v) => update({ typewriter: v })),
      check("Stavningskontroll", s.spellcheck, (v) => update({ spellcheck: v })),
      h("button", { class: "link", onclick: () => this.showDictionary() }, "Egen ordlista …"),
    );
  }

  private toggleFullscreen(): void {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen().catch(() => toast("Helskärm stöds inte här"));
  }

  // ---------------- globala händelser ----------------
  private bindGlobalEvents(): void {
    document.addEventListener("keydown", (e) => {
      if (isMod(e) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void this.save(true);
      } else if (isMod(e) && e.key === "/") {
        e.preventDefault();
        this.setView(this.editor.mode === "write" ? "markdown" : "write");
      } else if (isMod(e) && e.key.toLowerCase() === "j" && !this.aiButton.hidden) {
        e.preventDefault();
        this.toggleDrawer(this.aiDrawer);
      } else if (isMod(e) && e.key.toLowerCase() === "e") {
        e.preventDefault();
        void this.showExport();
      } else if (isMod(e) && e.key.toLowerCase() === "o") {
        e.preventDefault();
        this.toggleDrawer(this.docsDrawer);
      } else if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
        if (document.querySelector(".drawer.open, .popover.open")) {
          this.closeDrawers();
          this.editor.focus();
        }
      }
    });

    // Gränssnittet tonas ut när man skriver och tillbaka när musen rör sig.
    let lastX = 0;
    let lastY = 0;
    document.addEventListener("mousemove", (e) => {
      if (Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY) > 8) {
        document.body.classList.remove("typing");
      }
      lastX = e.clientX;
      lastY = e.clientY;
    });

    document.addEventListener("click", (e) => {
      const t = e.target as Node;
      if (
        this.settingsPanel.classList.contains("open") &&
        !this.settingsPanel.contains(t)
      ) {
        this.settingsPanel.classList.remove("open");
      }
      // Klick i texten stänger öppna lådor.
      if ((t as Element).closest?.(".page") && document.querySelector(".drawer.open")) {
        this.closeDrawers();
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") void this.flush();
    });
    window.addEventListener("beforeunload", (e) => {
      if (this.saveState === "dirty" || this.saveState === "saving") {
        void this.flush();
        e.preventDefault();
      }
    });
  }
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const app = new App(document.getElementById("app")!);
app.start().catch((e) => {
  document.getElementById("app")!.replaceChildren(
    h("p", { class: "fatal" }, `Kunde inte starta Word Work: ${errorText(e)}`),
  );
});
