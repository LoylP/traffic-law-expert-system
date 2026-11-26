"use client";

import { ArrowUp } from "lucide-react";
import { useEffect, type RefObject } from "react";

export const MAX_LENGTH = 2000; // ConsultRequest.message
const COUNTER_FROM = 400;

const QUICK_STARTS = [
  { label: "Vượt đèn đỏ", text: "Tôi đi xe máy vượt đèn đỏ" },
  { label: "Nồng độ cồn", text: "Tôi lái ô tô, đo được nồng độ cồn " },
  { label: "Quá tốc độ", text: "Tôi lái ô tô chạy  km/h trên đường giới hạn  km/h" },
  { label: "Mũ bảo hiểm", text: "Tôi đi xe máy không đội mũ bảo hiểm" },
  { label: "Đi ngược chiều", text: "Tôi đi xe máy ngược chiều trên đường một chiều" },
];

type ChatInputProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  busy: boolean;
  placeholder: string;
  showQuickStarts: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
};

export function ChatInput({
  value,
  onChange,
  onSend,
  busy,
  placeholder,
  showQuickStarts,
  inputRef,
}: ChatInputProps) {
  const canSend = value.trim().length > 0 && !busy;

  // Grow with the content up to the CSS max-height (6 lines).
  // A width change re-wraps the text (and the placeholder), so watch it too.
  useEffect(() => {
    const area = inputRef.current;
    if (!area) return;
    const fit = () => {
      area.style.height = "auto";
      area.style.height = `${area.scrollHeight}px`;
    };
    fit();
    let width = area.clientWidth;
    const observer = new ResizeObserver(() => {
      if (area.clientWidth === width) return;
      width = area.clientWidth;
      fit();
    });
    observer.observe(area);
    return () => observer.disconnect();
  }, [value, inputRef]);

  const submit = () => {
    if (canSend) onSend(value.trim());
  };

  return (
    <div className="space-y-2">
      {showQuickStarts && !value && (
        <div aria-label="Gợi ý nhanh" role="group" className="flex gap-2 overflow-x-auto p-1">
          {QUICK_STARTS.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => {
                onChange(item.text);
                inputRef.current?.focus();
              }}
              className="shrink-0 rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-fg-muted hover:border-accent-line hover:text-accent"
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        className="flex items-end gap-2 rounded-2xl border border-line-strong bg-surface p-2 shadow-card focus-within:border-accent"
      >
        <textarea
          ref={inputRef}
          rows={1}
          value={value}
          maxLength={MAX_LENGTH}
          aria-label="Mô tả tình huống"
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            // isComposing: Enter that only confirms a Vietnamese IME word.
            if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
            event.preventDefault();
            submit();
          }}
          className="max-h-[156px] min-h-10 flex-1 resize-none bg-transparent px-2 py-2 leading-6 outline-none placeholder:text-fg-subtle"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Gửi"
          title="Gửi"
          className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-fg hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ArrowUp size={18} aria-hidden />
        </button>
      </form>
      {value.length > COUNTER_FROM && (
        <p aria-live="polite" className="text-right text-xs text-fg-subtle tabular-nums">
          {value.length}/{MAX_LENGTH} ký tự
        </p>
      )}
    </div>
  );
}
