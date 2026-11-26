import { CopyButton } from "@/components/ui/CopyButton";
import { citationFull } from "@/lib/format";
import type { LegalCitation } from "@/types/chat";

export function CitationBlock({ citation }: { citation: LegalCitation }) {
  return (
    <section className="space-y-1.5">
      <h4 className="flex items-start justify-between gap-2 text-sm font-semibold">
        {citation.label}
        <CopyButton
          text={citationFull(citation.citation_id)}
          ariaLabel={`Sao chép trích dẫn ${citation.label}`}
          className="shrink-0 rounded-lg p-1.5 text-fg-subtle hover:bg-surface-2 hover:text-fg"
        >
          {null}
        </CopyButton>
      </h4>
      <blockquote className="rounded-r-lg border-l-3 border-accent-line bg-surface-2 px-3 py-2 text-[13px] break-words whitespace-pre-line text-fg-muted">
        {citation.text ?? "Không tìm thấy nguyên văn."}
      </blockquote>
    </section>
  );
}
