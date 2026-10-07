/** Utseende-inställningar. Typsnitt gäller alltid hela dokumentet (temaval). */

export type Theme = "auto" | "light" | "sepia" | "dark";
export type Font = "literata" | "source-sans" | "plex-mono" | "system-serif";

export interface Settings {
  theme: Theme;
  font: Font;
  size: number; // px
  lineHeight: number;
  width: number; // ch
  focusParagraph: boolean;
  typewriter: boolean;
  spellcheck: boolean;
}

export const FONTS: Record<Font, { label: string; stack: string }> = {
  literata: { label: "Literata (serif)", stack: '"Literata Variable", Georgia, serif' },
  "source-sans": {
    label: "Source Sans (sans-serif)",
    stack: '"Source Sans 3 Variable", system-ui, sans-serif',
  },
  "plex-mono": { label: "IBM Plex Mono (skrivmaskin)", stack: '"IBM Plex Mono", ui-monospace, monospace' },
  "system-serif": {
    label: "Systemets serif",
    stack: 'Charter, "Iowan Old Style", "Palatino Linotype", Georgia, serif',
  },
};

export const THEMES: Record<Theme, string> = {
  auto: "Följ systemet",
  light: "Ljust",
  sepia: "Sepia",
  dark: "Mörkt",
};

const DEFAULTS: Settings = {
  theme: "auto",
  font: "literata",
  size: 20,
  lineHeight: 1.7,
  width: 66,
  focusParagraph: false,
  typewriter: false,
  spellcheck: true,
};

const KEY = "ww.settings";

export function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    /* privat läge e.d. */
  }
  return { ...DEFAULTS };
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* ignorera */
  }
}

export function applySettings(s: Settings): void {
  const root = document.documentElement;
  if (s.theme === "auto") root.removeAttribute("data-theme");
  else root.dataset.theme = s.theme;
  root.style.setProperty("--doc-font", FONTS[s.font].stack);
  root.style.setProperty("--doc-size", `${s.size}px`);
  root.style.setProperty("--doc-leading", String(s.lineHeight));
  root.style.setProperty("--doc-width", `${s.width}ch`);
  document.body.classList.toggle("focus-paragraph", s.focusParagraph);
  document.body.classList.toggle("typewriter", s.typewriter);
}
