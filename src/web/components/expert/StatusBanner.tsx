import { CircleSlash, SearchX } from "lucide-react";

import { Button } from "@/components/ui/Button";

type StatusBannerProps = {
  status: "unknown" | "out_of_scope";
  reasons: string[];
  onSuggest?: (text: string) => void;
};

const CONTENT = {
  unknown: {
    icon: SearchX,
    title: "Chưa đủ căn cứ để kết luận",
    suggestions: [
      "Tôi đi xe máy và vượt đèn đỏ",
      "Tôi lái ô tô chạy 75 km/h trên đường giới hạn 60 km/h",
      "Tôi đi xe máy không đội mũ bảo hiểm",
    ],
  },
  out_of_scope: {
    icon: CircleSlash,
    title: "Ngoài phạm vi hệ thống",
    suggestions: [
      "Hôm nay tôi đi xe máy vượt đèn đỏ",
      "Ngày 10/03/2025 tôi lái ô tô vượt đèn đỏ",
    ],
  },
};

export function StatusBanner({ status, reasons, onSuggest }: StatusBannerProps) {
  const { icon: Icon, title, suggestions } = CONTENT[status];
  return (
    <section className="space-y-3 rounded-2xl border border-neutral-line bg-neutral-soft p-4">
      <div className="flex gap-2.5">
        <Icon size={20} aria-hidden className="mt-0.5 shrink-0 text-fg-muted" />
        <div className="min-w-0 space-y-1">
          <h3 className="font-semibold">{title}</h3>
          {reasons.map((reason) => (
            <p key={reason} className="text-sm break-words text-fg-muted">
              {reason}
            </p>
          ))}
        </div>
      </div>
      {onSuggest && (
        <div>
          <p className="mb-1.5 text-[13px] text-fg-muted">
            Gợi ý cách hỏi lại (bấm để điền vào ô nhập):
          </p>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((text) => (
              <Button key={text} onClick={() => onSuggest(text)} className="text-left">
                {text}
              </Button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
