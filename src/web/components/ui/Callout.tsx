import clsx from "clsx";
import type { LucideIcon } from "lucide-react";

const TONES = {
  neutral: "border-neutral-line bg-neutral-soft text-fg-muted",
  info: "border-accent-line bg-accent-soft text-fg",
  warn: "border-warn-line bg-warn-soft text-warn-fg",
} as const;

type CalloutProps = {
  icon: LucideIcon;
  tone?: keyof typeof TONES;
  children: React.ReactNode;
};

export function Callout({ icon: Icon, tone = "neutral", children }: CalloutProps) {
  return (
    <div className={clsx("flex gap-2.5 rounded-xl border px-3.5 py-2.5 text-[13px]", TONES[tone])}>
      <Icon size={18} aria-hidden className="mt-0.5 shrink-0" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}
