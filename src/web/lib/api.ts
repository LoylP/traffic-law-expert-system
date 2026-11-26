import type {
  ConsultRecord,
  ConsultResponse,
  HistoryItem,
  KnowledgeStats,
  LegacyMode,
  SearchResponse,
} from "@/types/chat";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const TIMEOUT_MS = 180_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      signal: AbortSignal.timeout(TIMEOUT_MS),
      ...init,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    throw new Error(
      timedOut
        ? "Máy chủ phản hồi quá lâu. Bạn hãy thử lại."
        : "Không kết nối được tới máy chủ. Kiểm tra API đã chạy chưa rồi thử lại.",
    );
  }
  if (!response.ok) {
    throw new Error(`Máy chủ báo lỗi (mã ${response.status}). Bạn hãy thử lại.`);
  }
  return (await response.json()) as T;
}

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(TIMEOUT_MS)])
      : AbortSignal.timeout(TIMEOUT_MS),
  });
}

export function consult(message: string, sessionId: string, signal?: AbortSignal) {
  return post<ConsultResponse>("/consult", { message, session_id: sessionId }, signal);
}

export type SearchOptions = { topK: number; alpha: number };

export function legacySearch(
  mode: LegacyMode,
  query: string,
  { topK, alpha }: SearchOptions,
  signal?: AbortSignal,
) {
  const body = mode === "hybrid" ? { query, top_k: topK, alpha } : { query, alpha };
  return post<SearchResponse>(`/search/${mode}`, body, signal);
}

export async function fetchHistory(limit = 200): Promise<HistoryItem[]> {
  const data = await request<{ items: HistoryItem[] }>(`/history?limit=${limit}`);
  return data.items;
}

export function fetchLabels() {
  return request<{ labels: Record<string, string> }>("/knowledge/labels");
}

export function fetchKnowledgeStats() {
  return request<KnowledgeStats>("/knowledge/stats");
}

export function consultRecordOf(item: HistoryItem): ConsultRecord | null {
  if (item.api_type !== "consult") return null;
  return (item.results[0] as ConsultRecord | undefined) ?? null;
}
