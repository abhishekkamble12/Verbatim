import { clearToken, cognitoEnabled, getToken } from "./auth";
import type { ChatAnswer, Conversation, Job, Notebook, Report, SourceList, StoredMessage, TraceStep } from "./types";

const USER_KEY = "citeguard.user";
export const getUser = (): string | null => {
  if (cognitoEnabled && !getToken()) return null; // the token lives per tab; a remembered name alone is not a session
  try { return localStorage.getItem(USER_KEY); } catch { return null; }
};
export const setUser = (id: string | null) => {
  try { id ? localStorage.setItem(USER_KEY, id) : localStorage.removeItem(USER_KEY); } catch { /* private mode */ }
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** One readable sentence per failure; the server's own detail wins when it gave one. */
export function describe(status: number, detail: unknown): string {
  if (status === 503 && typeof detail === "string") return `The language model is not configured: ${detail}`;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return `Invalid input: ${detail[0].msg}`;
  const generic: Record<number, string> = {
    401: "You are signed out.", 403: "Access denied.", 404: "Not found.", 422: "Invalid input.",
  };
  return generic[status] ?? `Something went wrong (HTTP ${status}).`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = getUser();
  const token = getToken();
  // Cognito build: the access token. Local dev build: the typed name (the API runs with AUTH_MODE=local).
  const identity: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : user ? { "X-User-Id": user } : {};
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...identity, ...init.headers },
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Is the API running?");
  }
  if (res.status === 401 && token) { // expired or revoked: back to the sign-in screen
    clearToken();
    window.location.reload();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, describe(res.status, body.detail));
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  notebooks: () => request<Notebook[]>("/notebooks"),
  createNotebook: (title: string) => post<Notebook>("/notebooks", { title }),
  sources: (nb: string) => request<SourceList>(`/notebooks/${nb}/sources`),
  sourceUrl: (id: string) => request<{ url: string }>(`/sources/${id}/download`),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  startJob: (id: string) => post(`/jobs/${id}/start`),
  presign: (nb: string, filename: string, fileSize?: number) =>
    post<{ job_id: string; upload_url: string }>(`/notebooks/${nb}/uploads`, { filename, file_size_bytes: fileSize }),
  chat: (nb: string, query: string, conversation_id: string | null) =>
    post<ChatAnswer>(`/notebooks/${nb}/chat`, { query, conversation_id }),
  conversations: (nb: string) => request<Conversation[]>(`/notebooks/${nb}/conversations`),
  messages: (conv: string) => request<StoredMessage[]>(`/conversations/${conv}/messages`),
  createReport: (nb: string, question: string) => post<{ job_id: string }>(`/notebooks/${nb}/reports`, { question }),
  report: (id: string) => request<Report>(`/reports/${id}`),
  trace: (id: string) => request<{ agent_steps: TraceStep[] }>(`/reports/${id}/trace`),
};

/** Browser sends the PDF straight to S3 (presigned URL), then tells the API to queue ingestion. */
export async function uploadPdf(nb: string, file: File): Promise<string> {
  const MAX_BYTES = 50 * 1024 * 1024;
  if (file.size > MAX_BYTES) {
    throw new ApiError(422, "File exceeds maximum upload size of 50MB.");
  }
  const { job_id, upload_url } = await api.presign(nb, file.name, file.size);
  let put: Response;
  try {
    put = await fetch(upload_url, { method: "PUT", body: file });
  } catch {
    throw new ApiError(0, "Upload to storage failed. Is S3 (LocalStack) running?");
  }
  if (!put.ok) throw new ApiError(put.status, "Upload to storage was rejected.");
  await api.startJob(job_id);
  return job_id;
}

/** Poll a job every 2s, easing to 5s, until it finishes. Returns a cancel function. */
export function watchJob(id: string, onUpdate: (job: Job) => void, onError: (e: Error) => void): () => void {
  let stopped = false;
  let delay = 2000;
  const tick = async () => {
    if (stopped) return;
    try {
      const job = await api.job(id);
      if (stopped) return;
      onUpdate(job);
      if (job.state === "completed" || job.state === "failed") return;
    } catch (e) {
      if (!stopped) onError(e as Error);
      return;
    }
    delay = Math.min(delay + 500, 5000);
    setTimeout(tick, delay);
  };
  setTimeout(tick, delay);
  return () => { stopped = true; };
}
