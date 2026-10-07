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
import { Decoration, DecorationSet } from "@tiptap/pm/view";

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
  onChange: (markdown: string) => void;
  onActivity: () => void;
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
      this.markdown = normalize(this.editor.getMarkdown());
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
      ],
      content: this.markdown,
      contentType: "markdown",
      editorProps: {
        // Webbläsarens stavningskontroll används tills egen finns (fas 2).
        attributes: { class: "prose", "aria-label": "Text", spellcheck: "true", lang: "sv" },
      },
      onUpdate: () => {
        this.wysiwygDirty = true;
        this.opts.onActivity();
        this.emitChange();
      },
      onSelectionUpdate: () => this.typewriterScroll(),
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
