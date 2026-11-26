"use client";

import { useSyncExternalStore } from "react";

import { consultRecordOf } from "@/lib/api";
import { parseServerTime, truncate } from "@/lib/format";
import type { ChatTurn, HistoryItem } from "@/types/chat";

/** The server keeps session facts for 30 minutes (pipeline.SESSION_TTL_SECONDS). */
export const SESSION_TTL_MS = 30 * 60 * 1000;

export type CaseSummary = { sessionId: string; title: string; time: string };

const KEY = "traffic-law:cases";
const MAX_CASES = 50;
const EMPTY: CaseSummary[] = [];
const listeners = new Set<() => void>();
let cache: CaseSummary[] | null = null;

function read(): CaseSummary[] {
  if (cache) return cache;
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    cache = Array.isArray(parsed)
      ? (parsed as CaseSummary[]).filter((c) => c?.sessionId && c.title && c.time)
      : EMPTY;
  } catch {
    cache = EMPTY; // private window or blocked storage
  }
  return cache;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Create or refresh a case; the title stays the first question. */
export function rememberCase(sessionId: string, firstQuestion: string) {
  const list = read();
  const existing = list.find((c) => c.sessionId === sessionId);
  cache = [
    {
      sessionId,
      title: existing?.title ?? truncate(firstQuestion),
      time: new Date().toISOString(),
    },
    ...list.filter((c) => c.sessionId !== sessionId),
  ].slice(0, MAX_CASES);
  try {
    localStorage.setItem(KEY, JSON.stringify(cache));
  } catch {
    // the in-memory list still works for this tab
  }
  listeners.forEach((notify) => notify());
}

export function useStoredCases() {
  return useSyncExternalStore(subscribe, read, () => EMPTY);
}

/** Browser-stored cases plus the consult records of /history, newest first. */
export function mergeCases(stored: CaseSummary[], history: HistoryItem[]): CaseSummary[] {
  const byId = new Map<string, CaseSummary>();
  // /history is newest first: walk it backwards so the first question names the case.
  for (const item of [...history].reverse()) {
    const record = consultRecordOf(item);
    if (!record) continue;
    const known = byId.get(record.session_id);
    byId.set(record.session_id, {
      sessionId: record.session_id,
      title: known?.title ?? truncate(item.original_query),
      time: parseServerTime(item.created_at).toISOString(),
    });
  }
  for (const entry of stored) {
    const known = byId.get(entry.sessionId);
    byId.set(entry.sessionId, {
      ...entry,
      time: known && known.time > entry.time ? known.time : entry.time,
    });
  }
  return [...byId.values()].sort((a, b) => b.time.localeCompare(a.time)).slice(0, MAX_CASES);
}

/** Rebuild a conversation from history records (oldest first). */
export function turnsFromHistory(sessionId: string, history: HistoryItem[]): ChatTurn[] {
  return [...history]
    .reverse()
    .flatMap((item): ChatTurn[] => {
      const record = consultRecordOf(item);
      if (record?.session_id !== sessionId) return [];
      const at = parseServerTime(item.created_at).toISOString();
      const question: ChatTurn = {
        id: `h${item.id}-q`,
        at,
        kind: "user",
        text: item.original_query,
      };
      const answer: ChatTurn = record.result
        ? { id: `h${item.id}-a`, at, kind: "consult", result: record.result }
        : { id: `h${item.id}-a`, at, kind: "archived", text: record.answer_text };
      return [question, answer];
    });
}
