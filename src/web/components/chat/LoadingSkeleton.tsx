"use client";

import clsx from "clsx";
import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

// The API does not stream progress: the steps follow typical timings.
const STAGES = [
  { after: 0, text: "Đang phân tích câu hỏi…" },
  { after: 5000, text: "Đang ánh xạ hành vi vào cơ sở tri thức…" },
  { after: 8000, text: "Đang suy luận và tính mức phạt…" },
  { after: 11000, text: "Đang soạn câu trả lời…" },
];

function Bar({ className }: { className: string }) {
  return <div className={clsx("animate-pulse rounded-lg bg-surface-2", className)} />;
}

export function LoadingSkeleton({ legacy = false }: { legacy?: boolean }) {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    const timers = STAGES.slice(1).map((item, index) =>
      setTimeout(() => setStage(index + 1), item.after),
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="animate-enter space-y-3">
      <p role="status" className="flex items-center gap-2 text-sm text-fg-muted">
        <LoaderCircle size={18} aria-hidden className="animate-spin text-accent" />
        {legacy ? "Đang tra cứu…" : STAGES[stage].text}
      </p>
      <div aria-hidden className="space-y-3">
        <div className="space-y-3 rounded-2xl border border-line bg-surface p-4">
          <div className="flex justify-between gap-4">
            <Bar className="h-10 w-2/5" />
            <Bar className="h-10 w-1/5" />
          </div>
          <Bar className="h-5 w-3/5" />
        </div>
        {[0, 1].map((card) => (
          <div key={card} className="space-y-3 rounded-2xl border border-line bg-surface p-4">
            <Bar className="h-5 w-4/5" />
            <Bar className="h-5 w-2/5" />
            <Bar className="h-2 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}
