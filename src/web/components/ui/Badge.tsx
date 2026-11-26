import clsx from "clsx";

const TONES = {
  neutral: "border-neutral-line bg-neutral-soft text-fg-muted",
  accent: "border-accent-line bg-accent-soft text-accent",
  warn: "border-warn-line bg-warn-soft text-warn-fg",
  danger: "border-danger-line bg-danger-soft text-danger-fg",
  good: "border-good-line bg-good-soft text-good-fg",
  bad: "border-bad-line bg-bad-soft text-bad-fg",
} as const;

export type Tone = keyof typeof TONES;

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
