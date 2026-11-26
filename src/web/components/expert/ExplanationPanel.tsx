import { BadgeAlert, BadgeCheck, ChevronDown, X } from "lucide-react";

import { CitationBlock } from "@/components/expert/CitationBlock";
import { EvidenceHighlight } from "@/components/expert/EvidenceHighlight";
import { FactTable } from "@/components/expert/FactTable";
import { PenaltySteps } from "@/components/expert/PenaltySteps";
import { ReasoningTimeline } from "@/components/expert/ReasoningTimeline";
import { Badge } from "@/components/ui/Badge";
import { IconButton } from "@/components/ui/Button";
import type { Explanation } from "@/types/chat";

function Section({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <details open={defaultOpen} className="group border-b border-line last:border-b-0">
      <summary className="flex list-none items-center gap-2 px-4 py-3 font-semibold hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
        <span className="flex-1">{title}</span>
        {count !== undefined && <span className="text-xs text-fg-subtle">{count}</span>}
        <ChevronDown size={18} aria-hidden className="text-fg-subtle group-open:rotate-180" />
      </summary>
      <div className="space-y-4 px-4 pt-1 pb-4">{children}</div>
    </details>
  );
}

function Faithfulness({ explanation }: { explanation: Explanation }) {
  if (explanation.legal_citations.length === 0) return <Badge>Chưa có trích dẫn</Badge>;
  return explanation.faithfulness_ok ? (
    <Badge tone="good">
      <BadgeCheck size={14} aria-hidden />
      Trích dẫn khớp trace
    </Badge>
  ) : (
    <Badge tone="warn">
      <BadgeAlert size={14} aria-hidden />
      Trích dẫn chưa khớp trace
    </Badge>
  );
}

type ExplanationPanelProps = {
  explanation: Explanation;
  /** What the user typed in this case, for evidence highlighting. */
  messages: string[];
  onClose?: () => void;
};

export function ExplanationPanel({ explanation, messages, onClose }: ExplanationPanelProps) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold">Vì sao?</h2>
          <Faithfulness explanation={explanation} />
        </div>
        {onClose && (
          <IconButton label="Đóng phần giải thích" onClick={onClose}>
            <X size={18} aria-hidden />
          </IconButton>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Section title="Dữ kiện" count={explanation.facts_used.length} defaultOpen>
          <EvidenceHighlight messages={messages} facts={explanation.facts_used} />
          <FactTable facts={explanation.facts_used} />
        </Section>
        <Section title="Chuỗi suy luận" count={explanation.chain.length} defaultOpen>
          <ReasoningTimeline steps={explanation.chain} />
        </Section>
        <Section title="Căn cứ pháp lý" count={explanation.legal_citations.length}>
          {explanation.legal_citations.map((citation) => (
            <CitationBlock key={citation.citation_id} citation={citation} />
          ))}
          {explanation.legal_citations.length === 0 && (
            <p className="text-sm text-fg-muted">Chưa có căn cứ được áp dụng.</p>
          )}
        </Section>
        <Section title="Tính mức phạt">
          <PenaltySteps lines={explanation.penalty_calc} />
        </Section>
      </div>
    </div>
  );
}
