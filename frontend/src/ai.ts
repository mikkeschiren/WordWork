/**
 * AI-panelen. AI:n föreslår – den skriver aldrig i texten.
 *
 * Det finns medvetet ingen "infoga"- eller "ersätt"-knapp: svaren visas bara här.
 * Citat i svaren som finns i texten blir klickbara och markerar stället i
 * texten, så att författaren själv kan ändra.
 */
import DOMPurify from "dompurify";
import { marked } from "marked";
import { api, type AIEvent, type AIModel, type AIStatus } from "./api";
import { h, modKey, toast } from "./ui";

interface Message {
  role: "user" | "assistant";
  content: string;
  label?: string; // visningstext för snabbval
  thinking?: string;
  meta?: string;
  error?: string;
  pending?: boolean;
  showThinking?: boolean;
}

export interface AIPanelDeps {
  drawer: HTMLElement;
  closeButton: () => HTMLElement;
  documentName: () => string | null;
  documentText: () => string; // Markdown
  plainText: () => string;
  selectionText: () => string;
  showInText: (phrase: string) => boolean;
  flush: () => Promise<void>;
}

export const QUICK_LABELS: Record<string, string> = {
  language: "Granska språket",
  repetition: "Hitta upprepningar",
  tighten: "Stramare text",
  structure: "Struktur och dramaturgi",
  facts: "Fakta att kontrollera",
};

const MODEL_KEY = "ww.aiModel";
const THINK_KEY = "ww.aiThink";

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* ignorera */
  }
}

marked.use({ gfm: true, breaks: false });

function renderMarkdown(md: string): string {
  const html = marked.parse(md, { async: false }) as string;
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["p", "br", "strong", "em", "ol", "ul", "li", "blockquote", "code", "pre", "h3", "h4", "hr", "del"],
    ALLOWED_ATTR: [],
  });
}

const QUOTE_RE = /[”"“„»]([^”"“„»«\n]{2,240}?)[”"“«]/g;

function normalizeSpace(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

export class AIPanel {
  private status: AIStatus | null = null;
  private models: AIModel[] = [];
  private modelError = "";
  private model = stored(MODEL_KEY) ?? "";
  private think = stored(THINK_KEY) !== "false";
  private conversations = new Map<string, Message[]>();
  private controller: AbortController | null = null;
  private list = h("div", { class: "ai-messages", "aria-live": "polite" });
  private scope = h("span", { class: "scope" });
  private input = h("textarea", {
    rows: 3,
    placeholder: "Fråga om texten, t.ex. ”Fungerar ingressen?”",
    "aria-label": "Fråga till AI-assistenten",
  }) as HTMLTextAreaElement;
  private sendBtn = h("button", { class: "primary" }, "Fråga");
  private renderTimer = 0;
  /** Markering som gjorts av ett klick på ett citat – ska inte ändra frågans omfång. */
  private citeSelection = "";

  constructor(private deps: AIPanelDeps) {
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        void this.ask(this.input.value);
      }
    });
    this.sendBtn.addEventListener("click", () => {
      if (this.controller) this.stop();
      else void this.ask(this.input.value);
    });
  }

  async init(): Promise<boolean> {
    try {
      this.status = await api.aiStatus();
    } catch {
      this.status = { enabled: false };
    }
    if (!this.status.enabled) return false;
    if (!this.model) this.model = this.status.default_model ?? "";
    return true;
  }

  get available(): boolean {
    return !!this.status?.enabled;
  }

  /** Varför AI-stödet är avstängt (t.ex. att servern inte kan nås). */
  get reason(): string {
    return this.status?.reason ?? "";
  }

  /**
   * Kontrollerar med jämna mellanrum om Ollama-servern går att nå. Appen fungerar
   * alltid; AI-funktionen slås bara på och av.
   */
  monitor(onChange: (available: boolean) => void, intervalMs = 60_000): void {
    const check = async () => {
      const before = this.available;
      const now = await this.init();
      if (now !== before) {
        if (!now) this.stop();
        if (now) this.models = []; // hämta modellistan på nytt
        onChange(now);
      }
    };
    window.setInterval(() => void check(), intervalMs);
    // Kolla direkt när fönstret får fokus igen (t.ex. efter att datorn sovit).
    window.addEventListener("focus", () => void check());
  }

  private get messages(): Message[] {
    const key = this.deps.documentName() ?? "";
    let m = this.conversations.get(key);
    if (!m) {
      m = [];
      this.conversations.set(key, m);
    }
    return m;
  }

  private async loadModels(): Promise<void> {
    try {
      const r = await api.aiModels();
      this.models = r.models;
      this.modelError = "";
      if (!this.models.some((m) => m.name === this.model)) {
        this.model = this.models.some((m) => m.name === r.default_model)
          ? r.default_model
          : (this.models[0]?.name ?? "");
      }
    } catch (e) {
      this.modelError = e instanceof Error ? e.message : String(e);
    }
  }

  /** Bygger panelen. Anropas när lådan öppnas. */
  async render(): Promise<void> {
    if (!this.status?.enabled) return;
    const d = this.deps.drawer;
    d.replaceChildren(
      h("div", { class: "drawer-head" }, this.deps.closeButton(), h("h2", {}, "AI-assistent"), this.scope),
      h("p", { class: "meta" }, "Laddar modeller …"),
    );
    this.updateScope();
    if (!this.models.length) await this.loadModels();

    const modelSelect = h("select", {
      "aria-label": "Modell",
      onchange: (e: Event) => {
        this.model = (e.target as HTMLSelectElement).value;
        store(MODEL_KEY, this.model);
      },
    });
    for (const m of this.models) {
      modelSelect.append(
        h("option", { value: m.name, selected: m.name === this.model }, `${m.name} · ${m.parameters || `${m.size_gb} GB`}`),
      );
    }
    const thinkBox = h("input", {
      type: "checkbox",
      checked: this.think,
      onchange: (e: Event) => {
        this.think = (e.target as HTMLInputElement).checked;
        store(THINK_KEY, String(this.think));
      },
    });

    const notice = this.status.external
      ? h(
          "p",
          { class: "ai-notice" },
          `När du frågar skickas texten till ${this.status.host}. AI:n föreslår – den skriver aldrig i din text.`,
        )
      : h("p", { class: "ai-notice local" }, "AI:n körs lokalt. Den föreslår – den skriver aldrig i din text.");

    const quick = h(
      "div",
      { class: "ai-quick" },
      ...Object.entries(QUICK_LABELS)
        .filter(([k]) => !this.status?.quick || this.status.quick.includes(k))
        .map(([key, label]) => h("button", { class: "chip", onclick: () => void this.ask("", key) }, label)),
    );

    d.replaceChildren(
      h("div", { class: "drawer-head" }, this.deps.closeButton(), h("h2", {}, "AI-assistent"), this.scope),
      notice,
      this.modelError
        ? h("p", { class: "ai-error" }, this.modelError)
        : h(
            "div",
            { class: "ai-settings" },
            h("label", { class: "field" }, h("span", {}, "Modell"), modelSelect),
            h(
              "label",
              { class: "check small", title: "Modellen resonerar innan den svarar – träffsäkrare men långsammare" },
              thinkBox,
              h("span", {}, "Tänk efter först (noggrannare)"),
            ),
          ),
      quick,
      this.list,
      h(
        "div",
        { class: "ai-composer" },
        this.input,
        h(
          "div",
          { class: "ai-actions" },
          h("button", { class: "link", onclick: () => this.clear() }, "Rensa samtalet"),
          h("span", { class: "meta" }, "Enter skickar · Shift+Enter ny rad"),
          this.sendBtn,
        ),
      ),
    );
    this.renderMessages();
  }

  focusInput(): void {
    this.input.focus();
  }

  /** Markerad text som frågan ska gälla (minst tre ord, inte en citatmarkering). */
  private scopedSelection(): string {
    const sel = this.deps.selectionText();
    if (this.citeSelection && normalizeSpace(sel) === this.citeSelection) return "";
    return (sel.match(/\S+/g)?.length ?? 0) >= 3 ? sel : "";
  }

  updateScope(): void {
    const sel = this.scopedSelection();
    const n = sel.match(/\S+/g)?.length ?? 0;
    this.scope.textContent = n >= 3 ? `Markering · ${n} ord` : "Hela texten";
    this.scope.title = n >= 3 ? "Frågan gäller i första hand det markerade avsnittet" : "Frågan gäller hela texten";
  }

  private clear(): void {
    this.stop();
    this.messages.length = 0;
    this.renderMessages();
  }

  private stop(): void {
    this.controller?.abort();
    this.controller = null;
    this.sendBtn.textContent = "Fråga";
  }

  /** Avbryt pågående svar (t.ex. vid byte av dokument). */
  reset(): void {
    this.stop();
    if (this.deps.drawer.classList.contains("open")) this.renderMessages();
  }

  async ask(prompt: string, quick?: string): Promise<void> {
    if (this.controller) return;
    prompt = prompt.trim();
    if (!prompt && !quick) return;
    if (!this.model) {
      toast("Ingen AI-modell är vald");
      return;
    }
    await this.deps.flush();
    const selection = this.scopedSelection();
    const msgs = this.messages;
    const history = msgs
      .filter((m) => !m.error && !m.pending && m.content)
      .map((m) => ({ role: m.role, content: m.content }));

    msgs.push({
      role: "user",
      content: quick ? "" : prompt,
      label: quick ? QUICK_LABELS[quick] : undefined,
    });
    const answer: Message = { role: "assistant", content: "", thinking: "", pending: true };
    msgs.push(answer);
    this.input.value = "";
    this.renderMessages();

    const started = performance.now();
    const ticker = window.setInterval(() => this.scheduleRender(), 1000);
    this.controller = new AbortController();
    this.sendBtn.textContent = "Stoppa";
    try {
      await api.aiChat(
        {
          model: this.model,
          think: this.think,
          prompt,
          quick,
          document: this.deps.documentText(),
          selection,
          history,
        },
        (e: AIEvent) => {
          if (e.type === "start") {
            const user = msgs[msgs.indexOf(answer) - 1];
            if (user && quick) user.content = e.question; // det faktiska snabbvalet följer med i historiken
          } else if (e.type === "thinking") answer.thinking += e.text;
          else if (e.type === "content") answer.content += e.text;
          else if (e.type === "done") {
            const tps = e.tokens_per_second ? ` · ${Math.round(e.tokens_per_second)} tokens/s` : "";
            answer.meta = `${e.model} · ${e.seconds} s${tps}`;
          } else if (e.type === "error") answer.error = e.message;
          this.scheduleRender();
        },
        this.controller.signal,
      );
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        answer.meta = "Avbrutet";
      } else {
        answer.error = e instanceof Error ? e.message : String(e);
      }
    } finally {
      window.clearInterval(ticker);
      answer.pending = false;
      if (!answer.meta && !answer.error) answer.meta = `${Math.round((performance.now() - started) / 1000)} s`;
      this.controller = null;
      this.sendBtn.textContent = "Fråga";
      this.renderMessages();
    }
  }

  private scheduleRender(): void {
    if (this.renderTimer) return;
    this.renderTimer = requestAnimationFrame(() => {
      this.renderTimer = 0;
      this.renderMessages();
    });
  }

  private renderMessages(): void {
    const msgs = this.messages;
    const stickToBottom = this.list.scrollHeight - this.list.scrollTop - this.list.clientHeight < 40;
    if (!msgs.length) {
      this.list.replaceChildren(
        h(
          "div",
          { class: "ai-empty" },
          h("p", {}, "Välj ett snabbval eller ställ en egen fråga om texten."),
          h(
            "p",
            { class: "meta" },
            `Markera ett avsnitt först om frågan gäller just det. Citat i svaren som finns i texten kan du klicka på för att hitta dem. Öppna panelen med ${modKey}+J.`,
          ),
        ),
      );
      return;
    }
    const plain = normalizeSpace(this.deps.plainText());
    this.list.replaceChildren(...msgs.map((m) => this.renderMessage(m, plain)));
    if (stickToBottom || msgs[msgs.length - 1]?.pending) this.list.scrollTop = this.list.scrollHeight;
  }

  private renderMessage(m: Message, plain: string): HTMLElement {
    if (m.role === "user") {
      return h("div", { class: "ai-msg user" }, m.label ? h("strong", {}, m.label) : m.content);
    }
    const el = h("div", { class: `ai-msg assistant${m.pending ? " pending" : ""}` });
    if (m.thinking) {
      const details = h(
        "details",
        { class: "ai-thinking", open: !!m.showThinking },
        h("summary", {}, m.pending && !m.content ? "Tänker …" : "Visa resonemang"),
        h("div", {}, m.thinking),
      ) as HTMLDetailsElement;
      details.addEventListener("toggle", () => (m.showThinking = details.open));
      el.append(details);
    } else if (m.pending && !m.content) {
      el.append(h("p", { class: "meta" }, this.think ? "Tänker …" : "Skriver …"));
    }
    if (m.content) {
      const body = h("div", { class: "ai-body" });
      body.innerHTML = renderMarkdown(m.content);
      if (!m.pending) this.linkQuotes(body, plain);
      el.append(body);
    }
    if (m.error) el.append(h("p", { class: "ai-error" }, m.error));
    if (m.meta) el.append(h("p", { class: "ai-meta" }, m.meta));
    return el;
  }

  /** Gör citat som finns i texten klickbara ("visa i texten"). */
  private linkQuotes(root: HTMLElement, plain: string): void {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    while (walker.nextNode()) nodes.push(walker.currentNode as Text);
    for (const node of nodes) {
      const text = node.data;
      QUOTE_RE.lastIndex = 0;
      let last = 0;
      const frag = document.createDocumentFragment();
      let changed = false;
      for (const m of text.matchAll(QUOTE_RE)) {
        const phrase = normalizeSpace(m[1].replace(/^[.…]+|[.…]+$/g, ""));
        if (phrase.length < 2 || !plain.includes(phrase)) continue;
        frag.append(text.slice(last, m.index));
        const btn = h(
          "button",
          {
            class: "cite",
            title: "Visa i texten",
            onclick: () => {
              this.citeSelection = phrase;
              if (!this.deps.showInText(phrase)) toast("Hittade inte frasen i texten");
              this.updateScope();
            },
          },
          m[0],
        );
        frag.append(btn);
        last = m.index! + m[0].length;
        changed = true;
      }
      if (changed) {
        frag.append(text.slice(last));
        node.replaceWith(frag);
      }
    }
  }
}
