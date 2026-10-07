/**
 * Högerklicksmeny i Skriv-vyn: rättningsförslag, egen ordlista och synonymer.
 * Ingenting ändras i texten förrän användaren själv väljer ett alternativ.
 */
import type { EditorView } from "@tiptap/pm/view";
import { TextSelection } from "@tiptap/pm/state";
import { api } from "./api";
import { wordAt, type SpellService, type WordRange } from "./spell";
import { h, toast } from "./ui";

interface MenuDeps {
  spell: SpellService;
  replace: (from: number, to: number, text: string) => void;
}

let current: HTMLElement | null = null;

export function closeMenu(): void {
  current?.remove();
  current = null;
}

document.addEventListener("mousedown", (e) => {
  if (current && !current.contains(e.target as Node)) closeMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMenu();
});
window.addEventListener("blur", closeMenu);
window.addEventListener("resize", closeMenu);

/** Behåll versal begynnelsebokstav om originalet hade det. */
function matchCase(original: string, replacement: string): string {
  if (original.length > 1 && original === original.toUpperCase()) return replacement.toUpperCase();
  if (original[0] === original[0].toUpperCase() && original[0] !== original[0].toLowerCase()) {
    return replacement[0].toUpperCase() + replacement.slice(1);
  }
  return replacement;
}

export function openContextMenu(event: MouseEvent, view: EditorView, deps: MenuDeps): boolean {
  const hit = view.posAtCoords({ left: event.clientX, top: event.clientY });
  if (!hit) return false;
  const range = wordAt(view.state, hit.pos);
  if (!range) return false;

  // Markera ordet så det syns vad menyn gäller.
  view.dispatch(
    view.state.tr.setSelection(TextSelection.create(view.state.doc, range.from, range.to)),
  );

  closeMenu();
  const menu = h("div", { class: "context-menu", role: "menu" });
  current = menu;

  const choose = (text: string) => {
    deps.replace(range.from, range.to, matchCase(range.word, text));
    closeMenu();
  };

  const misspelled = deps.spell.isMisspelled(range.word);
  if (misspelled) buildSpelling(menu, range, deps, choose);
  buildSynonyms(menu, range, choose);

  document.body.append(menu);
  position(menu, event.clientX, event.clientY);
  return true;
}

function item(label: string, onclick: () => void, cls = ""): HTMLButtonElement {
  return h("button", { class: `menu-item ${cls}`, role: "menuitem", onclick }, label);
}

function buildSpelling(
  menu: HTMLElement,
  range: WordRange,
  deps: MenuDeps,
  choose: (t: string) => void,
): void {
  const list = h("div", { class: "menu-group" }, h("div", { class: "menu-note" }, "Söker förslag …"));
  menu.append(
    h("div", { class: "menu-heading" }, `Stavning: ”${range.word}”`),
    list,
    item("Lägg till i egen ordlista", async () => {
      closeMenu();
      try {
        await deps.spell.addToDictionary(range.word);
        toast(`”${range.word}” finns nu i din ordlista`);
      } catch {
        toast("Kunde inte spara i ordlistan");
      }
    }),
    item("Ignorera i den här sessionen", () => {
      deps.spell.ignore(range.word);
      closeMenu();
    }),
    h("hr", {}),
  );
  api
    .suggest(range.word)
    .then(({ suggestions }) => {
      list.replaceChildren(
        ...(suggestions.length
          ? suggestions.map((s) => item(s, () => choose(s), "suggestion"))
          : [h("div", { class: "menu-note" }, "Inga förslag")]),
      );
      reposition(menu);
    })
    .catch(() => list.replaceChildren(h("div", { class: "menu-note" }, "Kunde inte hämta förslag")));
}

function buildSynonyms(menu: HTMLElement, range: WordRange, choose: (t: string) => void): void {
  const box = h("div", { class: "menu-group synonyms" }, h("div", { class: "menu-note" }, "Söker synonymer …"));
  menu.append(h("div", { class: "menu-heading" }, `Synonymer`), box);
  api
    .synonyms(range.word)
    .then(({ groups }) => {
      if (!groups.length) {
        box.replaceChildren(h("div", { class: "menu-note" }, `Inga synonymer för ”${range.word}”`));
        return;
      }
      const nodes: HTMLElement[] = [];
      for (const g of groups) {
        if (g.base_form || groups.length > 1) {
          nodes.push(h("div", { class: "menu-sub" }, g.base_form ? `${g.word} (grundform)` : g.word));
        }
        nodes.push(
          h(
            "div",
            { class: "chips" },
            ...g.synonyms.slice(0, 18).map((s) =>
              h("button", { class: "chip", role: "menuitem", onclick: () => choose(s) }, s),
            ),
          ),
        );
      }
      box.replaceChildren(...nodes);
      reposition(menu);
    })
    .catch(() => box.replaceChildren(h("div", { class: "menu-note" }, "Kunde inte hämta synonymer")));
}

function position(menu: HTMLElement, x: number, y: number): void {
  menu.dataset.x = String(x);
  menu.dataset.y = String(y);
  reposition(menu);
}

function reposition(menu: HTMLElement): void {
  const x = Number(menu.dataset.x);
  const y = Number(menu.dataset.y);
  const r = menu.getBoundingClientRect();
  const left = Math.min(x, window.innerWidth - r.width - 8);
  const top = y + r.height > window.innerHeight - 8 ? Math.max(8, y - r.height) : y;
  menu.style.left = `${Math.max(8, left)}px`;
  menu.style.top = `${top}px`;
}
