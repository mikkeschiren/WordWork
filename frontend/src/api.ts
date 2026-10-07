export interface DocumentInfo {
  id: string;
  name: string;
  modified: number;
  words: number;
}

export interface DocumentData {
  id: string;
  name: string;
  content: string;
  modified: number;
}

export interface Version {
  id: string;
  created: string;
  kind: "auto" | "manual" | "named" | "restore";
  label: string;
  words: number;
}

export interface SynonymGroup {
  word: string;
  base_form: boolean;
  synonyms: string[];
}

export interface ExportOptions {
  formats: { key: string; label: string; templates: boolean }[];
  templates: { key: string; label: string }[];
}

export interface AIStatus {
  enabled: boolean;
  configured?: boolean;
  reason?: string;
  host?: string;
  external?: boolean;
  default_model?: string;
  quick?: string[];
}

export interface AIModel {
  name: string;
  size_gb: number;
  parameters: string;
  thinking: boolean;
}

export type AIEvent =
  | { type: "start"; question: string }
  | { type: "thinking" | "content"; text: string }
  | { type: "done"; model: string; tokens: number; seconds: number; tokens_per_second: number | null }
  | { type: "error"; message: string };

export interface AIChatRequest {
  model: string;
  think: boolean;
  prompt?: string;
  quick?: string;
  document: string;
  selection: string;
  history: { role: "user" | "assistant"; content: string }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const raw = body instanceof Blob;
  const res = await fetch(`/api${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": raw ? "application/octet-stream" : "application/json" },
    body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {
      /* inget JSON-svar */
    }
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const doc = (name: string) => `/documents/${encodeURIComponent(name)}`;

export const api = {
  list: () => request<DocumentInfo[]>("GET", "/documents"),
  create: (name?: string, content = "") =>
    request<DocumentInfo>("POST", "/documents", { name, content }),
  get: (name: string) => request<DocumentData>("GET", doc(name)),
  save: (name: string, content: string, baseModified: number | null, snapshot = false) =>
    request<{ modified: number }>("PUT", doc(name), {
      content,
      base_modified: baseModified,
      snapshot,
    }),
  rename: (name: string, newName: string) =>
    request<DocumentInfo>("POST", `${doc(name)}/rename`, { name: newName }),
  remove: (name: string) => request<void>("DELETE", doc(name)),
  history: (name: string) => request<Version[]>("GET", `${doc(name)}/history`),
  version: (name: string, vid: string) =>
    request<{ id: string; content: string }>("GET", `${doc(name)}/history/${vid}`),
  snapshot: (name: string, label = "") =>
    request<{ created: boolean; version: Version | null }>("POST", `${doc(name)}/history`, {
      label,
    }),
  restore: (name: string, vid: string) =>
    request<{ modified: number; content: string }>(
      "POST",
      `${doc(name)}/history/${vid}/restore`,
    ),
  spellCheck: (words: string[]) =>
    request<{ misspelled: string[] }>("POST", "/spell/check", { words }),
  suggest: (word: string, limit = 6) =>
    request<{ word: string; suggestions: string[] }>(
      "GET",
      `/spell/suggest?word=${encodeURIComponent(word)}&limit=${limit}`,
    ),
  dictionary: () => request<{ words: string[] }>("GET", "/spell/dictionary"),
  dictionaryAdd: (word: string) =>
    request<{ words: string[] }>("POST", "/spell/dictionary", { word }),
  dictionaryRename: (word: string, newWord: string) =>
    request<{ words: string[] }>("PUT", `/spell/dictionary/${encodeURIComponent(word)}`, { word: newWord }),
  dictionaryReplace: (words: string[]) => request<{ words: string[] }>("PUT", "/spell/dictionary", { words }),
  dictionaryRemove: (word: string) =>
    request<{ words: string[] }>("DELETE", `/spell/dictionary/${encodeURIComponent(word)}`),
  synonyms: (word: string) =>
    request<{ word: string; groups: SynonymGroup[] }>(
      "GET",
      `/synonyms?word=${encodeURIComponent(word)}`,
    ),
  exportOptions: () => request<ExportOptions>("GET", "/export/formats"),
  exportUrl: (name: string, format: string, template: string) =>
    `/api${doc(name)}/export?format=${encodeURIComponent(format)}&template=${encodeURIComponent(template)}`,
  importFile: (file: File) =>
    request<DocumentInfo>("POST", `/import?filename=${encodeURIComponent(file.name)}`, file),
  aiStatus: () => request<AIStatus>("GET", "/ai/status"),
  aiModels: () => request<{ models: AIModel[]; default_model: string }>("GET", "/ai/models"),
  /** Strömmar AI-svaret som NDJSON-händelser. */
  async aiChat(body: AIChatRequest, onEvent: (e: AIEvent) => void, signal: AbortSignal): Promise<void> {
    const res = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok || !res.body) {
      let msg = res.statusText;
      try {
        msg = (await res.json()).detail ?? msg;
      } catch {
        /* inget JSON-svar */
      }
      throw new ApiError(res.status, msg);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) onEvent(JSON.parse(line) as AIEvent);
      }
    }
    if (buf.trim()) onEvent(JSON.parse(buf) as AIEvent);
  },
};
