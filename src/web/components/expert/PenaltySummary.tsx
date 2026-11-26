import { Badge } from "@/components/ui/Badge";
import { formatMoney, sanctionLabel } from "@/lib/format";
import type { ConsultResponse } from "@/types/chat";

export function PenaltySummary({ result }: { result: ConsultResponse }) {
  const provisional = result.status === "need_info";
  const { aggravating, mitigating, sanctions } = result;

  return (
    <section
      aria-label="Tổng hợp mức phạt"
      className="rounded-2xl border border-accent-line bg-surface p-4 shadow-card"
    >
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div>
          <p className="text-[13px] text-fg-subtle">
            {provisional ? "Tổng tiền phạt tạm tính" : "Tổng tiền phạt đề xuất"}
          </p>
          <p className="text-3xl leading-tight font-bold text-danger-fg tabular-nums">
            {formatMoney(result.total_recommended_fine)}
          </p>
        </div>
        <div className="@sm:text-right">
          <p className="text-[13px] text-fg-subtle">Điểm GPLX bị trừ</p>
          <p className="text-2xl leading-tight font-bold tabular-nums">
            {result.total_points_deducted}
            <span className="ml-1 text-sm font-medium text-fg-subtle">điểm</span>
          </p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
        {sanctions.map((sanction, index) => (
          <Badge key={index} tone="danger">
            {sanctionLabel(sanction)}
          </Badge>
        ))}
        {sanctions.length === 0 && <Badge>Không có hình thức bổ sung</Badge>}
        {aggravating.length > 0 && <Badge tone="bad">{aggravating.length} tình tiết tăng nặng</Badge>}
        {mitigating.length > 0 && <Badge tone="good">{mitigating.length} tình tiết giảm nhẹ</Badge>}
        {aggravating.length + mitigating.length === 0 && (
          <Badge>Không có tình tiết tăng nặng, giảm nhẹ</Badge>
        )}
      </div>
    </section>
  );
}
