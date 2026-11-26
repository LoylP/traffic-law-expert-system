"use client";

import clsx from "clsx";

import { fieldLabel } from "@/lib/labels";
import type { FactUsed } from "@/types/chat";

const GROUPS = [
  { name: "Phương tiện", color: "bg-(--hl-vehicle)", fields: ["vehicle_class", "subject"] },
  { name: "Hành vi", color: "bg-(--hl-act)", fields: ["acts", "free_behaviors", "no_helmet_who"] },
  {
    name: "Số đo",
    color: "bg-(--hl-measure)",
    fields: [
      "speed_limit_kmh",
      "actual_speed_kmh",
      "speed_over_kmh",
      "speed_band",
      "alcohol_level",
      "bac_blood_mg_100ml",
      "bac_breath_mg_l",
      "passengers_count",
      "drank_alcohol",
      "alcohol_test_refused",
    ],
  },
  { name: "Tình tiết", color: "bg-(--hl-circumstance)", fields: ["circumstances"] },
  {
    name: "Diễn biến",
    color: "bg-(--hl-event)",
    fields: ["officer_signal", "resistance", "consequence"],
  },
];
const OTHER = { name: "Khác", color: "bg-(--hl-other)", fields: [] as string[] };

export function factGroup(field: string) {
  return GROUPS.find((group) => group.fields.includes(field)) ?? OTHER;
}

type Span = { start: number; end: number; field: string };
type Segment = { text: string; field: string | null };

function segments(message: string, facts: FactUsed[]): Segment[] {
  const text = message.normalize("NFC");
  const haystack = text.toLocaleLowerCase("vi");
  const spans: Span[] = [];
  for (const fact of facts) {
    // One evidence string may hold several excerpts separated by ";".
    for (const part of (fact.evidence ?? "").split(";")) {
      const needle = part.trim().normalize("NFC").toLocaleLowerCase("vi");
      const start = needle ? haystack.indexOf(needle) : -1;
      if (start >= 0) spans.push({ start, end: start + needle.length, field: fact.field });
    }
  }
  // Paint long spans first so shorter ones inside them stay visible.
  spans.sort((a, b) => b.end - b.start - (a.end - a.start));
  const owner: (string | null)[] = new Array(text.length).fill(null);
  for (const span of spans) owner.fill(span.field, span.start, span.end);

  const result: Segment[] = [];
  for (let i = 0; i < text.length; i += 1) {
    const last = result[result.length - 1];
    if (last && last.field === owner[i]) last.text += text[i];
    else result.push({ text: text[i], field: owner[i] });
  }
  return result;
}

export function EvidenceHighlight({ messages, facts }: { messages: string[]; facts: FactUsed[] }) {
  const used = [...new Set(facts.filter((f) => f.evidence).map((f) => factGroup(f.field)))];
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-fg-subtle">Câu bạn đã nhập</p>
      {messages.map((message, index) => (
        <p key={index} className="rounded-xl bg-surface-2 px-3 py-2 leading-8 break-words">
          {segments(message, facts).map((segment, i) =>
            segment.field ? (
              <mark
                key={i}
                title={fieldLabel(segment.field)}
                className={clsx("rounded px-0.5 py-0.5 text-fg", factGroup(segment.field).color)}
              >
                {segment.text}
              </mark>
            ) : (
              <span key={i}>{segment.text}</span>
            ),
          )}
        </p>
      ))}
      {used.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-fg-muted">
          {used.map((group) => (
            <li key={group.name} className="inline-flex items-center gap-1.5">
              <span aria-hidden className={clsx("size-3 rounded-sm", group.color)} />
              {group.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
