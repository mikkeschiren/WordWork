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
import { DocEditor, type ViewMode } from "./editor";
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
import { confirm, countWords, formatDate, h, isMod, modKey, prompt, showModal, toast } from "./ui";

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
  private statusSave = h("span", { class: "save-state" });
  private docsDrawer = h("aside", { class: "drawer left", "aria-label": "Dokument" });
  private historyDrawer = h("aside", { class: "drawer right", "aria-label": "Versionshistorik" });
  private settingsPanel = h("div", { class: "popover", role: "dialog", "aria-label": "Utseende" });
  private banner = h("div", { class: "banner", role: "alert", hidden: true });

  constructor(root: HTMLElement) {
    applySettings(this.settings);

    const host = h("div", { class: "editor-host" });
    this.editor = new DocEditor({
      host,
      onChange: (md) => this.onChange(md),
      onActivity: () => document.body.classList.add("typing"),
    });
    this.editor.typewriter = this.settings.typewriter;

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
      ),
      this.titleBtn,
      h(
        "div",
        { class: "group" },
        h("div", { class: "segmented", role: "group", "aria-label": "Vy" }, ...Object.values(this.viewBtns)),
        h("button", { onclick: () => this.toggleDrawer(this.historyDrawer) }, "Historik"),
        h("button", { onclick: (e: Event) => this.toggleSettings(e) }, "Utseende"),
        h("button", { onclick: () => this.toggleFullscreen(), title: "Helskärm" }, "Helskärm"),
      ),
    );
    this.titleBtn.addEventListener("click", () => this.renameCurrent());

    const statusbar = h(
      "footer",
      { class: "chrome statusbar" },
      this.statusWords,
      this.statusChars,
      this.statusSave,
    );

    root.append(
      topbar,
      this.banner,
      h("main", { class: "page" }, host),
      statusbar,
      this.docsDrawer,
      this.historyDrawer,
      this.settingsPanel,
    );

    this.bindGlobalEvents();
    this.setView((localStorage.getItem(VIEW_KEY) as ViewMode) || "write", false);
  }

  // ---------------- uppstart ----------------
  async start(): Promise<void> {
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

  private updateStats(md: string): void {
    const plain = stripMarkdown(md);
    const words = countWords(plain);
    this.statusWords.textContent = `${words.toLocaleString("sv-SE")} ord`;
    this.statusChars.textContent = `${plain.replace(/\n/g, "").length.toLocaleString("sv-SE")} tecken`;
  }

  // ---------------- lådor & paneler ----------------
  private toggleDrawer(drawer: HTMLElement): void {
    const open = !drawer.classList.contains("open");
    this.closeDrawers();
    if (open) {
      drawer.classList.add("open");
      if (drawer === this.docsDrawer) void this.renderDocs();
      else void this.renderHistory();
    } else {
      this.editor.focus();
    }
  }

  private closeDrawers(): void {
    this.docsDrawer.classList.remove("open");
    this.historyDrawer.classList.remove("open");
    this.settingsPanel.classList.remove("open");
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
        h("h2", {}, "Dokument"),
        h("button", { onclick: () => this.newDocument() }, "Nytt"),
      ),
      list,
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

function stripMarkdown(md: string): string {
  return md
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*(?:[-*+]|\d+\.)\s+/gm, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_~`]/g, "");
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
