"use client";

import clsx from "clsx";
import { ChevronDown, Info } from "lucide-react";
import { useId, useState } from "react";

import { FineRangeBar } from "@/components/expert/FineRangeBar";
import { Badge } from "@/components/ui/Badge";
import { Callout } from "@/components/ui/Callout";
import { CopyButton } from "@/components/ui/CopyButton";
import { citationFull, citationShort, formatMoney, sanctionLabel } from "@/lib/format";
import type { ConsultViolation } from "@/types/chat";

export function ViolationCard({ violation }: { violation: ConsultViolation }) {
  const [expanded, setExpanded] = useState(false);
  const detailId = useId();
  const title = violation.description.replace(/[\s;.]+$/, "");

  return (
    <article className="space-y-3 rounded-2xl border border-line bg-surface p-4 shadow-card">
      <h3>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={detailId}
          onClick={() => setExpanded((value) => !value)}
          className="flex w-full items-start gap-2 rounded-lg text-left font-semibold"
        >
          <span className={clsx("min-w-0 flex-1", !expanded && "truncate")}>{title}</span>
          <ChevronDown
            size={18}
            aria-hidden
            className={clsx("mt-0.5 shrink-0 text-fg-subtle", expanded && "rotate-180")}
          />
        </button>
      </h3>

      <div id={detailId} hidden={!expanded}>
        <p className="mb-1 text-xs font-medium text-fg-subtle">Nguyên văn</p>
        <blockquote className="rounded-r-lg border-l-3 border-accent-line bg-surface-2 px-3 py-2 text-[13px] whitespace-pre-line text-fg-muted">
          {violation.legal_text ?? violation.description}
        </blockquote>
      </div>

      <CopyButton
        text={citationFull(violation.citation_id)}
        ariaLabel={`Sao chép trích dẫn ${citationFull(violation.citation_id)}`}
        className="rounded-full border border-accent-line bg-accent-soft px-3 py-1 text-xs font-semibold text-accent"
      >
        {citationShort(violation.citation_id)}
      </CopyButton>

      {violation.fine_range ? (
        <FineRangeBar
          range={violation.fine_range}
          recommended={violation.recommended_fine}
          allowed={violation.allowed_range_after_circumstances}
        />
      ) : (
        <p className="text-sm text-fg-muted">
          Không có khung phạt tiền. Mức đề xuất: {formatMoney(violation.recommended_fine)}.
        </p>
      )}

      {(violation.points_deducted > 0 || violation.sanctions.length > 0) && (
        <div className="flex flex-wrap gap-2">
          {violation.points_deducted > 0 && (
            <Badge tone="danger">Trừ {violation.points_deducted} điểm GPLX</Badge>
          )}
          {violation.sanctions.map((sanction, index) => (
            <Badge key={index} tone="danger">
              {sanctionLabel(sanction)}
            </Badge>
          ))}
        </div>
      )}

      {violation.org_rule_applied && (
        <p className="text-xs text-warn-fg">
          Khung đối với tổ chức được tạm tính bằng 2 lần khung cá nhân, cần đối chiếu NĐ 168/2024.
        </p>
      )}

      {violation.points_conditional.map((item) => (
        <Callout key={`${item.source}-${item.points}`} icon={Info}>
          Điểm trừ có điều kiện (chưa tự áp dụng): trừ {item.points} điểm GPLX nếu “
          {item.condition}” ({citationShort(item.source)}).
        </Callout>
      ))}
    </article>
  );
}
