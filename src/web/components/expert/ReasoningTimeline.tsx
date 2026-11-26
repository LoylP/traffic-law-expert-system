"use client";

import { Badge, type Tone } from "@/components/ui/Badge";
import { fieldLabel, useLabels } from "@/lib/labels";
import type { TraceStep } from "@/types/chat";

const TYPES: Record<TraceStep["type"], { label: string; tone: Tone }> = {
  derive: { label: "Suy diễn", tone: "accent" },
  classify: { label: "Phân loại", tone: "good" },
  escalate: { label: "Leo thang", tone: "bad" },
  exclude: { label: "Loại trừ", tone: "neutral" },
  ask: { label: "Hỏi lại", tone: "warn" },
  temporal: { label: "Thời gian", tone: "neutral" },
  note: { label: "Ghi chú", tone: "neutral" },
  ground: { label: "Ánh xạ ngữ nghĩa", tone: "accent" },
};

const isBlank = (value: unknown) =>
  value === null || value === "" || (Array.isArray(value) && value.length === 0);

function Entries({ title, values }: { title: string; values: Record<string, unknown> }) {
  const { valueLabel } = useLabels();
  // Retrieval scores of the grounder are debugging data.
  const entries = Object.entries(values).filter(
    ([key, value]) => key !== "candidates" && !(title === "Kết quả" && isBlank(value)),
  );
  if (entries.length === 0) return null;
  return (
    <div className="text-[13px]">
      <p className="text-xs font-semibold text-fg-subtle">{title}</p>
      <ul>
        {entries.map(([key, value]) => (
          <li key={key} className="break-words">
            <span className="text-fg-muted">{fieldLabel(key)}:</span> {valueLabel(value, key)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReasoningTimeline({ steps }: { steps: TraceStep[] }) {
  const { humanize } = useLabels();
  if (steps.length === 0) {
    return <p className="text-sm text-fg-muted">Không có luật nào được kích hoạt.</p>;
  }
  return (
    <ol className="ml-1.5 border-l border-line-strong">
      {steps.map((step, index) => {
        const type = TYPES[step.type] ?? { label: step.type, tone: "neutral" as const };
        const description = step.explain ?? step.source;
        return (
          <li key={`${step.rule_id}-${index}`} className="relative space-y-1.5 pb-5 pl-5 last:pb-0">
            <span
              aria-hidden
              className="absolute top-1.5 -left-[6.5px] size-3 rounded-full border-2 border-accent bg-surface"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={type.tone}>{type.label}</Badge>
              <span className="text-[11px] break-all text-fg-subtle">{step.rule_id}</span>
            </div>
            {description && <p className="text-sm break-words">{humanize(description)}</p>}
            <Entries title="Điều kiện khớp" values={step.matched_facts} />
            <Entries title="Kết quả" values={step.produced} />
          </li>
        );
      })}
    </ol>
  );
}
