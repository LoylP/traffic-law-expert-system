import { Scale } from "lucide-react";

export function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-fg">
        <Scale size={18} aria-hidden />
      </span>
      <span className="leading-tight font-semibold">Trợ lý Luật Giao thông</span>
    </div>
  );
}
