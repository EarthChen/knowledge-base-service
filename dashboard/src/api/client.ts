import type { BusinessWikiExportBody, BusinessWikiExportResponse } from "../hooks/wikiTypes";
import type {
  EnrichRequest,
  GraphInsightsReport,
  TaskInfo,
  WikiAsyncTask,
  WikiExportResult,
  WikiLintReport,
} from "./types";
import { getCurrentBusiness } from "../currentBusiness";

export const API_BASE = "/api/v1";
const STORAGE_KEY = "kb_api_token";

export function getToken(): string {
  return localStorage.getItem(STORAGE_KEY) || "";
}

export function setToken(value: string) {
  if (value) localStorage.setItem(STORAGE_KEY, value);
  else localStorage.removeItem(STORAGE_KEY);
}

export { getCurrentBusiness };

export function authHeaders(): Record<string, string> {
  const t = getToken();
  const biz = getCurrentBusiness();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (t) h.Authorization = `Bearer ${t}`;
  if (biz) h["X-Business-Id"] = biz;
  return h;
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/** Prefer FastAPI ``detail``, then unified ``ErrorResponse`` shape ({ error: { message } }). */
function messageFromFailedResponse(
  d: Record<string, unknown> | null,
  res: Response,
): string {
  if (d && typeof d.detail === "string") return d.detail;
  if (d && d.detail != null) return JSON.stringify(d.detail);
  const errField = d?.error;
  if (typeof errField === "string") return errField;
  if (errField && typeof errField === "object" && errField !== null && "message" in errField) {
    const m = (errField as { message?: unknown }).message;
    if (typeof m === "string" && m.trim()) return m;
    if (m != null) return JSON.stringify(m);
  }
  return res.statusText || "";
}

const DEFAULT_TIMEOUT_MS = 30_000;

export async function api<T = unknown>(
  path: string,
  options: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  let url: string;
  if (path.startsWith("http")) {
    const parsed = new URL(path, typeof window !== "undefined" ? window.location.href : undefined);
    if (typeof window !== "undefined" && parsed.origin !== window.location.origin) {
      throw new ApiError("Cross-origin API calls are not allowed", 0, null);
    }
    url = path;
  } else {
    url = API_BASE + path;
  }
  const { timeoutMs, ...fetchOpts } = options;
  const controller = new AbortController();
  const timeout = timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeout);
  const existingSignal = fetchOpts.signal;
  const onParentAbort = () => controller.abort();
  if (existingSignal) {
    existingSignal.addEventListener("abort", onParentAbort);
  }
  let res: Response;
  try {
    res = await fetch(url, {
      ...fetchOpts,
      signal: controller.signal,
      headers: { ...authHeaders(), ...(fetchOpts.headers as Record<string, string>) },
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(`Request timed out after ${timeout}ms`, 0, null);
    }
    throw e;
  } finally {
    clearTimeout(timer);
    if (existingSignal) {
      existingSignal.removeEventListener("abort", onParentAbort);
    }
  }
  const text = await res.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const d = data as Record<string, unknown> | null;
    const msg = messageFromFailedResponse(d, res);
    throw new ApiError(msg || "Request failed", res.status, data);
  }
  return data as T;
}

/** 触发业务摘要补全（POST /enrich）。`businessId` 写入 X-Business-Id。 */
export async function triggerEnrich(
  businessId: string,
  request: EnrichRequest,
): Promise<TaskInfo> {
  return api<TaskInfo>("/enrich", {
    method: "POST",
    body: JSON.stringify(request),
    headers: { "X-Business-Id": businessId },
  });
}

export async function wikiLint(repository: string, scope = "all"): Promise<WikiLintReport> {
  return api<WikiLintReport>(`/wiki/${encodeURIComponent(repository)}/lint`, {
    method: "POST",
    body: JSON.stringify({ scope }),
  });
}

export async function getGraphInsights(
  repository: string,
  businessId?: string,
): Promise<GraphInsightsReport> {
  let path = `/graph/insights/${encodeURIComponent(repository)}`;
  if (businessId) {
    path += `?business_id=${encodeURIComponent(businessId)}`;
  }
  return api<GraphInsightsReport>(path);
}

export async function wikiExportPreview(
  repository: string,
  targetDir: string,
): Promise<WikiExportResult> {
  return api<WikiExportResult>(`/wiki/${encodeURIComponent(repository)}/export/preview`, {
    method: "POST",
    body: JSON.stringify({ target_dir: targetDir }),
  });
}

export async function wikiExportExecute(
  repository: string,
  targetDir: string,
  selectedFiles?: string[],
): Promise<WikiExportResult> {
  return api<WikiExportResult>(`/wiki/${encodeURIComponent(repository)}/export/execute`, {
    method: "POST",
    body: JSON.stringify({ target_dir: targetDir, selected_files: selectedFiles }),
  });
}

export async function wikiGenerate(
  repository: string,
  scope: string,
  mode = "full",
  language = "en",
): Promise<TaskInfo> {
  return api<TaskInfo>("/wiki/generate", {
    method: "POST",
    body: JSON.stringify({ repository, scope, mode, language }),
  });
}

export async function wikiTaskStatus(taskId: string): Promise<WikiAsyncTask> {
  return api<WikiAsyncTask>(`/wiki/tasks/${encodeURIComponent(taskId)}`);
}

export async function businessWikiGenerate(
  businessId: string,
  language: string,
  incremental = true,
  mode: "structure" | "full" = "full",
): Promise<TaskInfo> {
  return api<TaskInfo>("/wiki/business/generate", {
    method: "POST",
    body: JSON.stringify({ business_id: businessId, language, incremental, mode }),
  });
}

export async function businessWikiTaskStatus(taskId: string): Promise<WikiAsyncTask> {
  return api<WikiAsyncTask>(`/wiki/business/tasks/${encodeURIComponent(taskId)}`);
}

export interface ActiveTasksResponse {
  tasks: WikiAsyncTask[];
  total: number;
}

export async function listActiveWikiTasks(): Promise<ActiveTasksResponse> {
  return api<ActiveTasksResponse>("/wiki/tasks/active");
}

export async function cancelWikiTask(taskId: string): Promise<{ task_id: string; status: string }> {
  return api<{ task_id: string; status: string }>(
    `/wiki/tasks/${encodeURIComponent(taskId)}/cancel`,
    { method: "POST" },
  );
}

export async function businessWikiExport(
  body: BusinessWikiExportBody,
): Promise<BusinessWikiExportResponse> {
  if (body.format === "git") {
    return api<BusinessWikiExportResponse>("/wiki/export", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  const url = `${API_BASE}/wiki/export`;
  const EXPORT_TIMEOUT_MS = 120_000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), EXPORT_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(`Request timed out after ${EXPORT_TIMEOUT_MS}ms`, 0, null);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(text || res.statusText || "Request failed", res.status, text);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = `${body.business_id}-wiki-${body.format}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);

  return { format: body.format, business_id: body.business_id };
}

export type SyncRepoAndWikiRequest = {
  repository: string;
  git_url?: string;
  branch?: string;
};

export type SyncRepoAndWikiResponse = {
  repository: string;
  directory: string;
  git_pull: string | Record<string, string>;
  index_stats: Record<string, number> | null;
  wiki_task_id: string | null;
  wiki_triggered: boolean;
};

export async function syncRepoAndWiki(
  body: SyncRepoAndWikiRequest,
): Promise<SyncRepoAndWikiResponse> {
  return api<SyncRepoAndWikiResponse>("/sync/repo-update-wiki", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export type WikiCrystallizeRequest = {
  repository: string;
  question: string;
  answer: string;
  sources: string[];
  conversation_id?: string | null;
  business_id?: string;
};

export type WikiCrystallizeResponse = {
  page_uid: string;
  title: string;
  path: string;
  conversation_id?: string | null;
};

export async function wikiCrystallize(
  body: WikiCrystallizeRequest,
): Promise<WikiCrystallizeResponse> {
  const businessId = body.business_id ?? getCurrentBusiness() ?? "default";
  return api<WikiCrystallizeResponse>("/wiki/ask/crystallize", {
    method: "POST",
    body: JSON.stringify({
      ...body,
      business_id: businessId,
    }),
  });
}
