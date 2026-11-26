import { Info, MessageSquarePlus, PanelRightOpen, ScanSearch } from "lucide-react";

import { BranchList } from "@/components/expert/BranchList";
import { FollowUpQuestion } from "@/components/expert/FollowUpQuestion";
import { PenaltySummary } from "@/components/expert/PenaltySummary";
import { StatusBanner } from "@/components/expert/StatusBanner";
import { ViolationCard } from "@/components/expert/ViolationCard";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { CopyButton } from "@/components/ui/CopyButton";
import type { ConsultResponse } from "@/types/chat";

export type ConsultActions = {
  onExplain?: () => void;
  onFollowUp?: () => void;
  onAnswer?: (reply: string) => void;
  onSuggest?: (text: string) => void;
};

type ConsultAnswerProps = ConsultActions & {
  result: ConsultResponse;
  explaining?: boolean;
};

export function ConsultAnswer({
  result,
  explaining = false,
  onExplain,
  onFollowUp,
  onAnswer,
  onSuggest,
}: ConsultAnswerProps) {
  const { status, violations, notes } = result;
  const stopped = status === "unknown" || status === "out_of_scope";

  return (
    <div className="@container space-y-3">
      {stopped ? (
        <StatusBanner
          status={status}
          reasons={notes.length ? notes : [result.summary_text]}
          onSuggest={onSuggest}
        />
      ) : (
        <p className="whitespace-pre-line">{result.summary_text}</p>
      )}

      {status === "need_info" && (
        <FollowUpQuestion
          key={result.questions[0]?.rule_id}
          questions={result.questions}
          known={result.explanation.facts_used}
          onAnswer={onAnswer}
        />
      )}

      {violations.length > 0 && (
        <>
          <PenaltySummary result={result} />
          <h2 className="pt-1 text-sm font-semibold text-fg-muted">
            {status === "need_info"
              ? "Hành vi đã xác định được (kết quả tạm thời)"
              : `${violations.length} hành vi vi phạm`}
          </h2>
          {violations.map((violation) => (
            <ViolationCard key={violation.citation_id} violation={violation} />
          ))}
        </>
      )}

      {result.branches && result.branches.length > 0 && (
        <BranchList branches={result.branches} dependsOn={result.depends_on ?? []} />
      )}

      <div className="flex flex-wrap gap-2">
        {onExplain && (
          <Button
            variant={explaining ? "primary" : "outline"}
            onClick={onExplain}
            aria-pressed={explaining}
          >
            <PanelRightOpen size={18} aria-hidden />
            Vì sao?
          </Button>
        )}
        <CopyButton
          text={result.answer_text}
          ariaLabel="Sao chép câu trả lời"
          className="min-h-9 rounded-xl px-3 text-sm font-medium text-fg-muted hover:bg-surface-2"
        >
          Sao chép
        </CopyButton>
        {onFollowUp && (
          <Button variant="ghost" onClick={onFollowUp}>
            <MessageSquarePlus size={18} aria-hidden />
            Hỏi tiếp
          </Button>
        )}
      </div>

      {!stopped &&
        notes.map((note) => (
          <Callout
            key={note}
            icon={note.includes("tìm kiếm ngữ nghĩa") ? ScanSearch : Info}
            tone={note.includes("tìm kiếm ngữ nghĩa") ? "info" : "neutral"}
          >
            {note}
          </Callout>
        ))}
    </div>
  );
}
