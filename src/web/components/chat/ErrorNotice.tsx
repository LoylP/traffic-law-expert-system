import { RotateCcw, WifiOff } from "lucide-react";

import { Button } from "@/components/ui/Button";

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-2xl border border-danger-line bg-danger-soft p-4"
    >
      <WifiOff size={20} aria-hidden className="shrink-0 text-danger-fg" />
      <div className="min-w-0 flex-1 basis-48">
        <p className="font-semibold text-danger-fg">Chưa nhận được câu trả lời</p>
        <p className="text-sm text-fg-muted">{message}</p>
      </div>
      {onRetry && (
        <Button onClick={onRetry}>
          <RotateCcw size={18} aria-hidden />
          Thử lại
        </Button>
      )}
    </div>
  );
}
