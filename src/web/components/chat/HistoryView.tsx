"use client";

import { ArrowLeft, History, Search, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorNotice } from "@/components/chat/ErrorNotice";
import { LegacyResults } from "@/components/chat/LegacyResults";
import { ConsultAnswer } from "@/components/expert/ConsultAnswer";
import { ExplanationPanel } from "@/components/expert/ExplanationPanel";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Badge } from "@/components/ui/Badge";
import { Button, IconButton } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { consultRecordOf, fetchHistory } from "@/lib/api";
import { turnsFromHistory } from "@/lib/cases";
import { formatDateTime, formatMoney, parseServerTime } from "@/lib/format";
import type { ConsultStatus, HistoryItem, LegacyMode, SearchResult } from "@/types/chat";

const FILTERS = [
  { value: "all", label: "Tất cả" },
  { value: "consult", label: "Tư vấn (Expert)" },
  { value: "hybrid", label: "Tra cứu hybrid" },
  { value: "llm", label: "Tra cứu LLM" },
] as const;

type Filter = (typeof FILTERS)[number]["value"];

const STATUS_LABELS: Record<ConsultStatus, string> = {
  answered: "Đã kết luận",
  need_info: "Cần bổ sung",
  unknown: "Chưa đủ căn cứ",
  out_of_scope: "Ngoài phạm vi",
};

const modeLabel = (type: string) => FILTERS.find((f) => f.value === type)?.label ?? type;

function Detail({ item, history }: { item: HistoryItem; history: HistoryItem[] }) {
  const record = consultRecordOf(item);
  if (record) {
    // What the user had typed in this case up to this answer.
    const messages = turnsFromHistory(
      record.session_id,
      history.filter((other) => other.id <= item.id),
    ).flatMap((turn) => (turn.kind === "user" ? [turn.text] : []));
    return (
      <div className="space-y-4">
        {record.result ? (
          <>
            <div className="px-4">
              <ConsultAnswer result={record.result} />
            </div>
            <div className="border-t border-line">
              <ExplanationPanel explanation={record.result.explanation} messages={messages} />
            </div>
          </>
        ) : (
          <p className="px-4 whitespace-pre-line">{record.answer_text}</p>
        )}
      </div>
    );
  }
  const mode: LegacyMode = item.api_type === "llm" ? "llm" : "hybrid";
  const results = item.results as SearchResult[];
  return (
    <div className="px-4">
      <LegacyResults
        response={{
          success: true,
          api_type: mode,
          original_query: item.original_query,
          processed_query: item.processed_query,
          results,
          best_result: results[0] ?? null,
        }}
      />
    </div>
  );
}

function HistoryCard({ item, onOpen }: { item: HistoryItem; onOpen: () => void }) {
  const record = consultRecordOf(item);
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="w-full space-y-2 rounded-2xl border border-line bg-surface p-4 text-left shadow-card hover:border-accent-line"
      >
        <span className="flex flex-wrap items-center gap-2">
          <Badge tone={record ? "accent" : "neutral"}>{modeLabel(item.api_type)}</Badge>
          {record && <Badge>{STATUS_LABELS[record.status] ?? record.status}</Badge>}
          <span className="ml-auto text-xs text-fg-subtle tabular-nums">
            {formatDateTime(parseServerTime(item.created_at))}
          </span>
        </span>
        <span className="line-clamp-2 block font-medium break-words">{item.original_query}</span>
        <span className="block text-[13px] text-fg-muted tabular-nums">
          {record ? (
            <>
              {record.violations.length} vi phạm · Tổng tiền phạt đề xuất{" "}
              <strong className="font-semibold text-danger-fg">
                {formatMoney(record.total_recommended_fine)}
              </strong>
            </>
          ) : (
            `${item.results.length} kết quả tra cứu`
          )}
        </span>
      </button>
    </li>
  );
}

export function HistoryView() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<HistoryItem | null>(null);

  const load = useCallback(() => {
    fetchHistory()
      .then((data) => {
        setItems(data);
        setState("ready");
      })
      .catch((reason: Error) => {
        setError(reason.message);
        setState("error");
      });
  }, []);

  useEffect(load, [load]);

  const needle = query.trim().toLocaleLowerCase("vi");
  const visible = items.filter(
    (item) =>
      (filter === "all" || item.api_type === filter) &&
      item.original_query.toLocaleLowerCase("vi").includes(needle),
  );

  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-14 max-w-4xl items-center gap-2 px-2 sm:px-4">
          <Link
            href="/"
            aria-label="Quay lại trang tư vấn"
            className="flex size-10 items-center justify-center rounded-xl text-fg-muted hover:bg-surface-2"
          >
            <ArrowLeft size={18} aria-hidden />
          </Link>
          <h1 className="flex-1 font-semibold">Lịch sử tra cứu</h1>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-4 px-4 py-6">
        <label className="flex min-h-11 items-center gap-2 rounded-xl border border-line-strong bg-surface px-3 focus-within:outline-2 focus-within:outline-accent">
          <Search size={18} aria-hidden className="text-fg-subtle" />
          <span className="sr-only">Tìm trong lịch sử</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Tìm theo nội dung câu hỏi"
            className="min-w-0 flex-1 bg-transparent py-2 outline-none"
          />
        </label>
        <div role="group" aria-label="Lọc theo chế độ" className="flex flex-wrap gap-2">
          {FILTERS.map((option) => (
            <Button
              key={option.value}
              variant={filter === option.value ? "primary" : "outline"}
              aria-pressed={filter === option.value}
              onClick={() => setFilter(option.value)}
              className="rounded-full"
            >
              {option.label}
            </Button>
          ))}
        </div>

        {state === "loading" && (
          <div role="status" className="space-y-3">
            <span className="sr-only">Đang tải lịch sử…</span>
            {[0, 1, 2].map((row) => (
              <div key={row} className="h-24 animate-pulse rounded-2xl bg-surface-2" />
            ))}
          </div>
        )}
        {state === "error" && (
          <ErrorNotice
            message={error}
            onRetry={() => {
              setState("loading");
              load();
            }}
          />
        )}
        {state === "ready" && visible.length === 0 && (
          <div className="py-12 text-center text-fg-muted">
            <History size={32} aria-hidden className="mx-auto mb-2 text-fg-subtle" />
            {items.length ? "Không có bản ghi khớp bộ lọc." : "Chưa có lịch sử."}
          </div>
        )}
        {state === "ready" && visible.length > 0 && (
          <>
            <p className="text-xs text-fg-subtle">
              {visible.length} bản ghi (tối đa 200 bản ghi mới nhất)
            </p>
            <ul className="space-y-3">
              {visible.map((item) => (
                <HistoryCard key={item.id} item={item} onOpen={() => setSelected(item)} />
              ))}
            </ul>
          </>
        )}
      </main>

      <Sheet
        open={selected !== null}
        onClose={() => setSelected(null)}
        side="center"
        label="Kết quả đã lưu"
      >
        {selected && (
          <>
            <div className="flex items-start gap-2 border-b border-line px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-xs text-fg-subtle">
                  Chỉ xem · {modeLabel(selected.api_type)} ·{" "}
                  {formatDateTime(parseServerTime(selected.created_at))}
                </p>
                <h2 className="font-semibold break-words">{selected.original_query}</h2>
              </div>
              <IconButton label="Đóng" onClick={() => setSelected(null)}>
                <X size={18} aria-hidden />
              </IconButton>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto pt-4">
              <Detail key={selected.id} item={selected} history={items} />
            </div>
          </>
        )}
      </Sheet>
    </div>
  );
}
