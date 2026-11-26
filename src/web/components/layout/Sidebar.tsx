"use client";

import clsx from "clsx";
import { ChevronDown, Database, History, SlidersHorizontal, SquarePen } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Brand } from "@/components/layout/Brand";
import { KnowledgeDialog } from "@/components/layout/KnowledgeDialog";
import { Button } from "@/components/ui/Button";
import type { SearchOptions } from "@/lib/api";
import type { CaseSummary } from "@/lib/cases";
import { dayGroup } from "@/lib/format";
import type { ChatMode } from "@/types/chat";

export type SidebarProps = {
  cases: CaseSummary[];
  activeId: string;
  onNewCase: () => void;
  onOpenCase: (sessionId: string) => void;
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  searchOptions: SearchOptions;
  onSearchOptionsChange: (options: SearchOptions) => void;
};

const MODES: { value: ChatMode; label: string }[] = [
  { value: "expert", label: "Tư vấn (Expert)" },
  { value: "hybrid", label: "Tra cứu cũ: hybrid" },
  { value: "llm", label: "Tra cứu cũ: LLM" },
];

const LINK =
  "flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-fg-muted hover:bg-surface-2 hover:text-fg";

function NumberSetting({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-[13px] text-fg-muted">
      {label}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (event.target.value !== "" && next >= min && next <= max) onChange(next);
        }}
        className="w-20 rounded-lg border border-line-strong bg-surface px-2 py-1 tabular-nums"
      />
    </label>
  );
}

export function Sidebar({
  cases,
  activeId,
  onNewCase,
  onOpenCase,
  mode,
  onModeChange,
  searchOptions,
  onSearchOptionsChange,
}: SidebarProps) {
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const groups = new Map<string, CaseSummary[]>();
  for (const item of cases) {
    const day = dayGroup(new Date(item.time));
    groups.set(day, [...(groups.get(day) ?? []), item]);
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3">
      <div className="px-1 py-1">
        <Brand />
      </div>
      <Button variant="primary" onClick={onNewCase} className="min-h-11 w-full">
        <SquarePen size={18} aria-hidden />
        Vụ việc mới
      </Button>

      <nav aria-label="Vụ việc gần đây" className="min-h-0 flex-1 overflow-y-auto">
        {groups.size === 0 && (
          <p className="px-3 py-2 text-[13px] text-fg-subtle">Chưa có vụ việc nào.</p>
        )}
        {[...groups].map(([day, items]) => (
          <section key={day} className="mb-3">
            <h2 className="px-3 py-1 text-xs font-semibold text-fg-subtle">{day}</h2>
            <ul>
              {items.map((item) => (
                <li key={item.sessionId}>
                  <button
                    type="button"
                    title={item.title}
                    aria-current={item.sessionId === activeId ? "true" : undefined}
                    onClick={() => onOpenCase(item.sessionId)}
                    className={clsx(
                      "block w-full truncate rounded-xl px-3 py-2 text-left text-sm",
                      item.sessionId === activeId
                        ? "bg-accent-soft font-medium text-accent"
                        : "text-fg-muted hover:bg-surface-2 hover:text-fg",
                    )}
                  >
                    {item.title}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>

      <div className="space-y-0.5 border-t border-line pt-2">
        <Link href="/history" className={LINK}>
          <History size={18} aria-hidden />
          Lịch sử tra cứu
        </Link>
        <button type="button" className={LINK} onClick={() => setKnowledgeOpen(true)}>
          <Database size={18} aria-hidden />
          Cơ sở tri thức
        </button>
        <details className="group" open={mode !== "expert"}>
          <summary className={clsx(LINK, "list-none [&::-webkit-details-marker]:hidden")}>
            <SlidersHorizontal size={18} aria-hidden />
            <span className="flex-1">Nâng cao</span>
            <ChevronDown size={18} aria-hidden className="group-open:rotate-180" />
          </summary>
          <div className="space-y-2 px-3 py-2">
            <fieldset className="space-y-1">
              <legend className="sr-only">Chế độ</legend>
              {MODES.map((option) => (
                <label key={option.value} className="flex items-center gap-2 text-[13px]">
                  <input
                    type="radio"
                    name="chat-mode"
                    checked={mode === option.value}
                    onChange={() => onModeChange(option.value)}
                    className="accent-(--primary)"
                  />
                  {option.label}
                </label>
              ))}
            </fieldset>
            {mode !== "expert" && (
              <>
                {mode === "hybrid" && (
                  <NumberSetting
                    label="Số kết quả (top_k)"
                    value={searchOptions.topK}
                    min={1}
                    max={20}
                    step={1}
                    onChange={(topK) => onSearchOptionsChange({ ...searchOptions, topK })}
                  />
                )}
                <NumberSetting
                  label="Trọng số BM25 (alpha)"
                  value={searchOptions.alpha}
                  min={0}
                  max={1}
                  step={0.1}
                  onChange={(alpha) => onSearchOptionsChange({ ...searchOptions, alpha })}
                />
              </>
            )}
          </div>
        </details>
      </div>
      <KnowledgeDialog open={knowledgeOpen} onClose={() => setKnowledgeOpen(false)} />
    </div>
  );
}
