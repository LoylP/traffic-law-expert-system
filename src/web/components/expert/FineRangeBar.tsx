import clsx from "clsx";

import { formatMoney } from "@/lib/format";

type FineRangeBarProps = {
  range: [number, number];
  recommended: number;
  allowed: [number, number] | null;
};

/** Min–max bar with the midpoint and the recommended fine. */
export function FineRangeBar({ range: [min, max], recommended, allowed }: FineRangeBarProps) {
  const middle = (min + max) / 2;
  const position = (value: number) =>
    max === min ? 50 : Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
  const direction = recommended > middle ? "up" : recommended < middle ? "down" : "mid";
  const note = {
    up: "Cao hơn mức trung bình do tình tiết tăng nặng",
    down: "Thấp hơn mức trung bình do tình tiết giảm nhẹ",
    mid: "Áp dụng mức trung bình của khung",
  }[direction];
  const shaded = allowed && allowed[1] > allowed[0] ? allowed : null;

  return (
    <figure
      aria-label={`Khung phạt từ ${formatMoney(min)} đến ${formatMoney(max)}, mức trung bình ${formatMoney(middle)}, mức đề xuất ${formatMoney(recommended)}. ${note}.`}
      className="tabular-nums"
    >
      <div aria-hidden className="relative mx-2 h-6">
        <div className="absolute inset-x-0 top-2 h-2 rounded-full bg-surface-2 ring-1 ring-line ring-inset" />
        {shaded && (
          <div
            className={clsx(
              "absolute top-2 h-2 rounded-full",
              direction === "down" ? "bg-good-line" : "bg-bad-line",
            )}
            style={{
              left: `${position(shaded[0])}%`,
              width: `${position(shaded[1]) - position(shaded[0])}%`,
            }}
          />
        )}
        <div
          className="absolute top-0.5 h-5 w-0.5 -translate-x-1/2 bg-fg-subtle"
          style={{ left: `${position(middle)}%` }}
        />
        <div
          className="absolute top-1 size-4 -translate-x-1/2 rounded-full border-[3px] border-surface bg-primary shadow ring-1 ring-primary"
          style={{ left: `${position(recommended)}%` }}
        />
      </div>
      <div aria-hidden className="flex justify-between text-xs text-fg-subtle">
        <span>{formatMoney(min)}</span>
        <span>{formatMoney(max)}</span>
      </div>
      <figcaption className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-3 w-0.5 bg-fg-subtle" />
          Trung bình {formatMoney(middle)}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-full bg-primary" />
          Đề xuất <strong className="font-semibold text-fg">{formatMoney(recommended)}</strong>
        </span>
        <span
          className={clsx(
            "basis-full",
            direction === "up" && "text-bad-fg",
            direction === "down" && "text-good-fg",
          )}
        >
          {note}.
        </span>
      </figcaption>
    </figure>
  );
}
