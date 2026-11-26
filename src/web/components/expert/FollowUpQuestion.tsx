"use client";

import { CircleHelp, SendHorizontal } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/Button";
import { fieldLabel, useLabels } from "@/lib/labels";
import type { FactUsed, Question } from "@/types/chat";

type FollowUpQuestionProps = {
  questions: Question[];
  known: FactUsed[];
  /** Absent when the question was already answered or the case is read-only. */
  onAnswer?: (reply: string) => void;
};

export function FollowUpQuestion({ questions, known, onAnswer }: FollowUpQuestionProps) {
  // Asked one at a time: a bare number is matched to the first pending question.
  const [question, ...later] = questions;
  const [value, setValue] = useState("");
  const inputId = useId();
  const { valueLabel } = useLabels();
  if (!question) return null;

  const numeric = question.input_type === "number";
  const disabled = !onAnswer;
  const recorded = known.map((fact) => {
    const text = `${fieldLabel(fact.field)}: ${valueLabel(fact.value, fact.field)}`;
    return fact.origin === "derived" ? `${text} (suy ra từ ${fact.derived_from})` : text;
  });

  return (
    <section
      aria-label="Cần bổ sung thông tin"
      className="space-y-3 rounded-2xl border-2 border-warn-line bg-warn-soft p-4"
    >
      <div className="flex gap-2.5">
        <CircleHelp size={20} aria-hidden className="mt-0.5 shrink-0 text-warn-fg" />
        <div>
          <p className="text-xs font-semibold text-warn-fg">Cần bổ sung thông tin</p>
          <p className="font-semibold">{question.text}</p>
        </div>
      </div>

      {question.options.length > 0 && (
        <div role="group" aria-label={question.text} className="flex flex-wrap gap-2">
          {question.options.map((option) => (
            <Button
              key={String(option.value)}
              disabled={disabled}
              onClick={() => onAnswer?.(option.label)}
              className="min-h-11 px-4"
            >
              {option.label}
            </Button>
          ))}
        </div>
      )}
      {numeric && (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const reply = value.trim();
            if (!reply) return;
            onAnswer?.(question.unit ? `${reply} ${question.unit}` : reply);
          }}
        >
          <label htmlFor={inputId} className="sr-only">
            {question.text}
          </label>
          <div className="flex min-h-11 min-w-0 flex-1 items-center rounded-xl border border-line-strong bg-surface px-3 focus-within:outline-2 focus-within:outline-accent sm:max-w-64">
            <input
              id={inputId}
              disabled={disabled}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              placeholder="Hoặc nhập số đo"
              className="min-w-0 flex-1 bg-transparent py-2 tabular-nums outline-none"
            />
            {question.unit && <span className="pl-2 text-sm text-fg-subtle">{question.unit}</span>}
          </div>
          <Button
            type="submit"
            variant="primary"
            disabled={disabled || !value.trim()}
            className="min-h-11"
          >
            <SendHorizontal size={18} aria-hidden />
            Trả lời
          </Button>
        </form>
      )}

      {later.length > 0 && (
        <p className="text-[13px] text-fg-muted">
          Sẽ hỏi tiếp: {later.map((item) => item.text).join(" ")}
        </p>
      )}
      {recorded.length > 0 && (
        <p className="border-t border-warn-line pt-2 text-[13px] text-fg-muted">
          <span className="font-semibold">Đã ghi nhận:</span> {recorded.join(" · ")}
        </p>
      )}
    </section>
  );
}
