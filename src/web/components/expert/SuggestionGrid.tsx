import {
  Beer,
  Gauge,
  HardHat,
  type LucideIcon,
  MessageCircleQuestion,
  Siren,
  TrafficCone,
} from "lucide-react";

type Suggestion = { icon: LucideIcon; title: string; text: string };

export const SUGGESTIONS: Suggestion[] = [
  { icon: TrafficCone, title: "Vượt đèn đỏ", text: "Tôi đi xe máy vượt đèn đỏ" },
  {
    icon: Beer,
    title: "Nồng độ cồn, tái phạm",
    text: "Tôi uống bia rồi lái ô tô, bị đo được 0,3 mg/l khí thở, trước đây đã từng bị phạt lỗi này",
  },
  {
    icon: HardHat,
    title: "Không đội mũ bảo hiểm",
    text: "Tôi chở vợ và 2 con trên xe máy, không ai đội mũ bảo hiểm",
  },
  {
    icon: Siren,
    title: "Bỏ chạy khi bị dừng xe",
    text: "Tôi đi xe máy thấy CSGT ra hiệu dừng xe thì bỏ chạy, còn chửi CSGT",
  },
  {
    icon: Gauge,
    title: "Quá tốc độ gây tai nạn",
    text: "Tôi lái ô tô chạy 85 km/h trên đường giới hạn 60 km/h và gây tai nạn",
  },
  { icon: MessageCircleQuestion, title: "Mô tả còn thiếu dữ kiện", text: "nhậu xong chạy xe về" },
];

export function SuggestionGrid({ onPick }: { onPick: (text: string) => void }) {
  return (
    <ul className="grid gap-3 @md:grid-cols-2 @2xl:grid-cols-3">
      {SUGGESTIONS.map(({ icon: Icon, title, text }) => (
        <li key={title}>
          <button
            type="button"
            onClick={() => onPick(text)}
            className="flex h-full w-full flex-col gap-2 rounded-2xl border border-line bg-surface p-4 text-left shadow-card transition-colors hover:border-accent-line hover:bg-accent-soft"
          >
            <span className="flex items-center gap-2 font-semibold">
              <Icon size={18} aria-hidden className="shrink-0 text-accent" />
              {title}
            </span>
            <span className="text-[13px] text-fg-muted">“{text}”</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
