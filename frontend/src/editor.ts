/**
 * Editorn: två vyer över samma Markdown-text.
 *
 *  - "write":    WYSIWYG-lik vy (TipTap/ProseMirror). Endast formatering som
 *                Markdown kan uttrycka finns i schemat – inga typsnitt, färger,
 *                understrykning osv. Inklistrad formatering som inte är Markdown
 *                rensas bort automatiskt av schemat.
 *  - "markdown": källtexten i ett textfält.
 *
 * Markdown-strängen är alltid sanningen. Den skrivs bara om från WYSIWYG-vyn
 * när användaren faktiskt redigerar där.
 */
import { Editor, Extension } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";
import { Placeholder } from "@tiptap/extensions";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";
import { TextSelection } from "@tiptap/pm/state";
import { setHighlight, spellExtension, WordHighlight, type SpellService } from "./spell";

export type ViewMode = "write" | "markdown";

/** Markerar stycket där markören står (för fokusläge med dimning). */
const CurrentBlock = Extension.create({
  name: "currentBlock",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("currentBlock"),
        props: {
          decorations(state) {
            const { $from } = state.selection;
            if ($from.depth < 1) return DecorationSet.empty;
            const start = $from.before(1);
            const node = state.doc.child($from.index(0));
            return DecorationSet.create(state.doc, [
              Decoration.node(start, start + node.nodeSize, { class: "is-current" }),
            ]);
          },
        },
      }),
    ];
  },
});

export interface EditorOptions {
  host: HTMLElement;
  spell: SpellService;
  onChange: (markdown: string) => void;
  onActivity: () => void;
  onSelection?: () => void;
  onContextMenu?: (event: MouseEvent, view: EditorView) => boolean;
}

export class DocEditor {
  private host: HTMLElement;
  private wysiwygEl: HTMLDivElement;
  private sourceEl: HTMLTextAreaElement;
  private editor: Editor | null = null;
  private markdown = "";
  private wysiwygDirty = false;
  private changeTimer: number | undefined;
  mode: ViewMode = "write";
  typewriter = false;

  constructor(private opts: EditorOptions) {
    this.host = opts.host;
    this.wysiwygEl = document.createElement("div");
    this.wysiwygEl.className = "wysiwyg";
    this.sourceEl = document.createElement("textarea");
    this.sourceEl.className = "source";
    this.sourceEl.spellcheck = true;
    this.sourceEl.lang = "sv";
    this.sourceEl.placeholder = "Skriv här …";
    this.sourceEl.setAttribute("aria-label", "Markdown-källtext");
    this.host.append(this.wysiwygEl, this.sourceEl);

    this.sourceEl.addEventListener("input", () => {
      this.markdown = this.sourceEl.value;
      this.autoGrow();
      this.opts.onActivity();
      this.emitChange();
    });
    window.addEventListener("resize", () => this.autoGrow());
  }

  /** Läser in ett nytt dokument (nollställer ångra-historiken). */
  load(markdown: string): void {
    this.markdown = markdown;
    this.wysiwygDirty = false;
    this.render();
  }

  getMarkdown(): string {
    if (this.wysiwygDirty && this.editor) {
      // Frontmatter visas inte i Skriv-vyn och sätts tillbaka orört.
      this.markdown = splitFrontmatter(this.markdown).frontmatter + normalize(this.editor.getMarkdown());
      this.wysiwygDirty = false;
    }
    return this.markdown;
  }

  setMode(mode: ViewMode): void {
    if (mode === this.mode) return;
    this.getMarkdown(); // ta med ev. ändringar från WYSIWYG
    this.mode = mode;
    this.render();
    this.focus();
  }

  focus(): void {
    if (this.mode === "write") this.editor?.commands.focus();
    else this.sourceEl.focus();
  }

  /** Löptext utan Markdown-syntax (stycken åtskilda av tomrad). */
  getPlainText(): string {
    if (this.editor) return this.editor.getText({ blockSeparator: "\n\n" });
    return stripMarkdown(splitFrontmatter(this.markdown).body);
  }

  /** Markerad text i Skriv-vyn (tom sträng om inget är markerat). */
  getSelectionText(): string {
    if (!this.editor) return "";
    const { from, to, empty } = this.editor.state.selection;
    return empty ? "" : this.editor.state.doc.textBetween(from, to, "\n\n", " ");
  }

  /** Markerar alla förekomster av ett ord och scrollar till den första. */
  highlight(word: string | null): void {
    if (!this.editor) return;
    const first = setHighlight(this.editor.view, word);
    if (first !== null) this.scrollToPos(first);
  }

  /** Letar upp en textbit (t.ex. en mening) och markerar den. */
  selectText(text: string): boolean {
    if (!this.editor) return false;
    const needle = text.slice(0, 80);
    const { doc } = this.editor.state;
    let found: { from: number; to: number } | null = null;
    doc.descendants((node, pos) => {
      if (found || !node.isTextblock) return !found;
      const blockText = node.textBetween(0, node.content.size, " ", " ");
      const idx = blockText.indexOf(needle);
      if (idx >= 0) {
        const from = pos + 1 + idx;
        found = { from, to: Math.min(from + text.length, pos + 1 + node.content.size) };
      }
      return false;
    });
    if (!found) return false;
    const { from, to } = found;
    const view = this.editor.view;
    view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc, from, to)));
    view.focus();
    this.scrollToPos(from);
    return true;
  }

  private scrollToPos(pos: number): void {
    if (!this.editor) return;
    try {
      const coords = this.editor.view.coordsAtPos(pos);
      window.scrollBy({ top: coords.top - window.innerHeight * 0.4, behavior: "smooth" });
    } catch {
      /* ignorera */
    }
  }

  /** Byter ut text i ett intervall (används av rättningar och synonymer). */
  replaceRange(from: number, to: number, text: string): void {
    if (!this.editor) return;
    const view = this.editor.view;
    view.dispatch(view.state.tr.insertText(text, from, to));
    view.focus();
  }

  private render(): void {
    this.host.dataset.mode = this.mode;
    if (this.mode === "write") {
      this.sourceEl.hidden = true;
      this.wysiwygEl.hidden = false;
      this.mountWysiwyg();
    } else {
      this.editor?.destroy();
      this.editor = null;
      this.wysiwygEl.hidden = true;
      this.sourceEl.hidden = false;
      this.sourceEl.value = this.markdown;
      this.autoGrow();
    }
  }

  private mountWysiwyg(): void {
    this.editor?.destroy();
    this.wysiwygEl.replaceChildren();
    this.editor = new Editor({
      element: this.wysiwygEl,
      extensions: [
        StarterKit.configure({
          underline: false, // finns inte i Markdown
          link: { openOnClick: false, autolink: true },
        }),
        Markdown.configure({ indentation: { style: "space", size: 2 } }),
        Placeholder.configure({ placeholder: "Skriv här …" }),
        CurrentBlock,
        spellExtension(this.opts.spell),
        WordHighlight,
      ],
      content: splitFrontmatter(this.markdown).body,
      contentType: "markdown",
      editorProps: {
        // Egen stavningskontroll i Skriv-vyn; webbläsarens används i Markdown-vyn.
        attributes: { class: "prose", "aria-label": "Text", spellcheck: "false", lang: "sv" },
        handleDOMEvents: {
          contextmenu: (view, event) => {
            if (event.shiftKey || !this.opts.onContextMenu) return false;
            if (this.opts.onContextMenu(event, view)) {
              event.preventDefault();
              return true;
            }
            return false;
          },
        },
      },
      onUpdate: () => {
        this.wysiwygDirty = true;
        this.opts.onActivity();
        this.emitChange();
      },
      onSelectionUpdate: () => {
        this.typewriterScroll();
        this.opts.onSelection?.();
      },
    });
  }

  private emitChange(): void {
    window.clearTimeout(this.changeTimer);
    this.changeTimer = window.setTimeout(() => {
      this.opts.onChange(this.getMarkdown());
    }, 250);
  }

  private typewriterScroll(): void {
    if (!this.typewriter || !this.editor) return;
    const { view } = this.editor;
    try {
      const coords = view.coordsAtPos(view.state.selection.head);
      const target = window.innerHeight * 0.45;
      const delta = coords.top - target;
      if (Math.abs(delta) > 4) window.scrollBy({ top: delta, behavior: "smooth" });
    } catch {
      /* positionen kan saknas precis när editorn byggs om */
    }
  }

  private autoGrow(): void {
    const ta = this.sourceEl;
    if (ta.hidden) return;
    ta.style.height = "auto";
    ta.style.height = `${ta.scrollHeight}px`;
  }
}

/** En enda avslutande radbrytning – stabila filer och diffar. */
function normalize(md: string): string {
  // Tomma rader i slutet av ett citat ("> " utan text) är bara skräp från Enter.
  const trimmed = md.replace(/\s+$/, "").replace(/(?:\n>[ \t]*)+$/, "").replace(/\s+$/, "");
  return trimmed ? `${trimmed}\n` : "";
}

export function stripMarkdown(md: string): string {
  return md
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*(?:[-*+]|\d+\.)\s+/gm, "")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_~`]/g, "");
}

/**
 * YAML-frontmatter i början av filen (--- … --- eller --- … ...), inklusive
 * tomraderna efter. Den redigeras inte i Skriv-vyn utan bevaras exakt.
 * Som i Pandoc får raden efter inledande --- inte vara tom (då är det en avgränsningslinje).
 */
const FRONTMATTER_RE = /^\uFEFF?---[ \t]*\r?\n(?![ \t]*\r?\n)(?:[\s\S]*?\r?\n)?(?:---|\.\.\.)[ \t]*(?:\r?\n|$)(?:[ \t]*\r?\n)*/;

export function splitFrontmatter(md: string): { frontmatter: string; body: string } {
  const m = FRONTMATTER_RE.exec(md);
  if (!m) return { frontmatter: "", body: md };
  return { frontmatter: m[0], body: md.slice(m[0].length) };
}
