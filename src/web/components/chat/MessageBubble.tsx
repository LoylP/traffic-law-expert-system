import { ErrorNotice } from "@/components/chat/ErrorNotice";
import { LegacyResults } from "@/components/chat/LegacyResults";
import { ConsultAnswer, type ConsultActions } from "@/components/expert/ConsultAnswer";
import { formatTime } from "@/lib/format";
import type { ChatTurn } from "@/types/chat";

type MessageBubbleProps = ConsultActions & {
  turn: ChatTurn;
  explaining: boolean;
  onRetry?: () => void;
};

export function MessageBubble({ turn, explaining, onRetry, ...actions }: MessageBubbleProps) {
  if (turn.kind === "user") {
    return (
      <div data-turn="user" className="animate-enter flex scroll-mt-4 flex-col items-end gap-1">
        <p className="max-w-[88%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 break-words whitespace-pre-wrap text-primary-fg">
          {turn.text}
        </p>
        <time dateTime={turn.at} className="text-xs text-fg-subtle">
          {formatTime(turn.at)}
        </time>
      </div>
    );
  }
  return (
    <div className="animate-enter">
      {turn.kind === "consult" && (
        <ConsultAnswer result={turn.result} explaining={explaining} {...actions} />
      )}
      {turn.kind === "legacy" && <LegacyResults response={turn.response} />}
      {turn.kind === "archived" && (
        <p className="rounded-2xl border border-line bg-surface p-4 whitespace-pre-line">
          {turn.text}
        </p>
      )}
      {turn.kind === "error" && <ErrorNotice message={turn.message} onRetry={onRetry} />}
    </div>
  );
}
