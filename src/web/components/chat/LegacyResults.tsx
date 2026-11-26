"use client";

import { Badge } from "@/components/ui/Badge";
import { formatMoney } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import type { SearchResponse } from "@/types/chat";

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

function fineText(min: unknown, max: unknown) {
  const [low, high] = [min, max].map((v) => (typeof v === "number" ? formatMoney(v) : null));
  return low && high ? `${low} – ${high}` : "Không rõ";
}

/** Results of the old /search/hybrid and /search/llm endpoints. */
export function LegacyResults({ response }: { response: SearchResponse }) {
  const { idLabel } = useLabels();
  const results =
    response.api_type === "llm"
      ? response.best_result
        ? [response.best_result]
        : []
      : (response.results ?? []);

  return (
    <div className="space-y-3">
      {response.processed_query && (
        <p className="text-sm text-fg-muted">Câu truy vấn đã chuẩn hoá: {response.processed_query}</p>
      )}
      <p className="font-medium">
        {results.length
          ? `${results.length} kết quả tra cứu (không qua suy luận)`
          : "Không tìm thấy kết quả phù hợp."}
      </p>
      {results.map((result) => {
        const node = result.raw_node;
        const score = result.scores?.hybrid;
        return (
          <article
            key={result.violation_id}
            className="space-y-2 rounded-2xl border border-line bg-surface p-4 shadow-card"
          >
            <h3 className="font-semibold">
              {text(node.description) || text(node.normalized_violation)}
            </h3>
            <div className="flex flex-wrap gap-2">
              <Badge tone="accent">{text(node.legal_basis) || text(node.citation_id)}</Badge>
              {text(node.vehicle_class) && <Badge>{idLabel(text(node.vehicle_class))}</Badge>}
              {score !== undefined && <Badge>Độ khớp {score.toFixed(3)}</Badge>}
            </div>
            <p className="text-sm tabular-nums">
              Khung phạt: <strong>{fineText(node.fine_min, node.fine_max)}</strong>
            </p>
          </article>
        );
      })}
    </div>
  );
}
