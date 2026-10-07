/**
 * Textstatistik och läsbarhet.
 *
 * LIX (läsbarhetsindex, C-H Björnsson 1968):
 *   LIX = ord/meningar + (långa ord × 100)/ord, där långa ord har fler än 6 bokstäver.
 * OVIX (ordvariationsindex):
 *   OVIX = log(ord) / log(2 − log(unika ord)/log(ord))
 */
import { WORD_RE } from "./spell";

export interface TextStats {
  words: number;
  uniqueWords: number;
  chars: number;
  charsNoSpaces: number;
  sentences: number;
  paragraphs: number;
  longWords: number;
  lix: number | null;
  ovix: number | null;
  avgSentenceLength: number;
  avgWordLength: number;
  readingMinutes: number;
  longestSentences: { text: string; words: number }[];
  frequency: { word: string; count: number }[];
}

export interface LixLevel {
  max: number;
  label: string;
  example: string;
}

/** Tolkningsskala enligt lix.se. */
export const LIX_SCALE: LixLevel[] = [
  { max: 25, label: "Mycket lätt", example: "Barnböcker" },
  { max: 30, label: "Lätt", example: "Enkla texter, ungdomsböcker" },
  { max: 40, label: "Medelsvår", example: "Normal tidningstext, skönlitteratur" },
  { max: 50, label: "Svår", example: "Sakprosa, populärvetenskap" },
  { max: 60, label: "Mycket svår", example: "Facktexter" },
  { max: Infinity, label: "Extremt svår", example: "Byråkratsvenska, forskning" },
];

export function lixLevel(lix: number): LixLevel {
  return LIX_SCALE.find((l) => lix < l.max) ?? LIX_SCALE[LIX_SCALE.length - 1];
}

/** Vanliga svenska funktionsord som döljs i ordfrekvenslistan som standard. */
export const STOPWORDS = new Set(
  `och i att det som en på är av för med till den har de inte om ett han men var jag sig
  från vi så kan man när år säger hon under också efter eller nu sin där vid mot ska skulle
  kommer ut får finns vara hade alla andra mycket än här då sedan över bara in blir upp även
  vad få två vill ha många hur mer går sitt du mellan blev bli genom vår vilket utan något
  dem dig mig oss er ni honom henne hans hennes deras dess denna detta dessa vars vilken
  vilka sina sitt min mitt mina din ditt dina sådan sådant sådana själv jo ja nej ju väl
  redan aldrig alltid inget ingen inga någon några allt hela samma varit vart skall kunde
  ville måste bör borde låt man en ett åt utom hos innan medan eftersom fast om än både
  varken samt dock bl.a t.ex`.split(/\s+/),
);

// Förkortningar vars punkter inte ska räknas som meningsslut.
const ABBREVIATIONS =
  /\b(?:t\.ex|bl\.a|s\.k|d\.v\.s|dvs|m\.m|m\.fl|o\.s\.v|osv|t\.o\.m|f\.d|p\.g\.a|e\.d|e\.dyl|resp|ca|kl|nr|s|jfr|fr\.o\.m|t\.v|a\.k\.a|f\.ö|i\.o\.m|o\.d)\./giu;

/** Delar upp text i meningar. Stycken utan avslutande skiljetecken (t.ex. rubriker) räknas som egna meningar. */
export function splitSentences(text: string): string[] {
  const out: string[] = [];
  for (const para of text.split(/\n\s*\n/)) {
    const masked = para.replace(ABBREVIATIONS, (m) => m.replace(/\./g, "\u0000"));
    for (const raw of masked.split(/(?<=[.!?:…]["”’»)]*)\s+/u)) {
      const s = raw.replace(/\u0000/g, ".").replace(/\s+/g, " ").trim();
      if (s && WORD_RE.test(s)) out.push(s);
      WORD_RE.lastIndex = 0;
    }
  }
  return out;
}

function words(text: string): string[] {
  return (text.match(WORD_RE) ?? []).filter((w) => /\p{L}/u.test(w));
}

export function analyze(text: string, opts: { includeStopwords?: boolean; top?: number } = {}): TextStats {
  const ws = words(text);
  const n = ws.length;
  const lower = ws.map((w) => w.toLocaleLowerCase("sv"));
  const unique = new Set(lower);
  const sentences = splitSentences(text);
  const sentenceCount = Math.max(sentences.length, n ? 1 : 0);
  const longWords = ws.filter((w) => [...w.replace(/[-'’]/g, "")].length > 6).length;
  const letters = ws.reduce((sum, w) => sum + [...w].length, 0);

  const lix = n && sentenceCount ? n / sentenceCount + (longWords * 100) / n : null;
  let ovix: number | null = null;
  if (n > 1 && unique.size < n) {
    ovix = Math.log(n) / Math.log(2 - Math.log(unique.size) / Math.log(n));
  }

  const counts = new Map<string, number>();
  for (const w of lower) {
    if (!opts.includeStopwords && STOPWORDS.has(w)) continue;
    counts.set(w, (counts.get(w) ?? 0) + 1);
  }
  const frequency = [...counts.entries()]
    .map(([word, count]) => ({ word, count }))
    .sort((a, b) => b.count - a.count || a.word.localeCompare(b.word, "sv"))
    .slice(0, opts.top ?? 40);

  const longestSentences = sentences
    .map((s) => ({ text: s, words: words(s).length }))
    .sort((a, b) => b.words - a.words)
    .slice(0, 5)
    .filter((s) => s.words > 0);

  const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim()).length;

  return {
    words: n,
    uniqueWords: unique.size,
    chars: text.replace(/\n/g, "").length,
    charsNoSpaces: text.replace(/\s/g, "").length,
    sentences: sentences.length,
    paragraphs,
    longWords,
    lix,
    ovix,
    avgSentenceLength: sentenceCount ? n / sentenceCount : 0,
    avgWordLength: n ? letters / n : 0,
    readingMinutes: n / 200, // ca 200 ord/minut för svensk löptext
    longestSentences,
    frequency,
  };
}
