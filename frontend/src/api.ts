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

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
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
};
