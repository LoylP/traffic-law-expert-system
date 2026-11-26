"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";

import { IconButton } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { fetchKnowledgeStats } from "@/lib/api";
import type { KnowledgeStats, VerifiedCount } from "@/types/chat";

const RULE_FILES: Record<string, string> = {
  ask: "Luật hỏi bổ sung",
  classify_auto: "Luật phân loại sinh tự động",
  classify_core: "Luật phân loại viết tay",
  derive: "Luật suy diễn",
  escalate: "Luật leo thang",
  note: "Luật ghi chú",
  temporal: "Luật thời gian",
};

function Rows({ rows }: { rows: [string, VerifiedCount][] }) {
  return (
    <table className="w-full text-sm tabular-nums">
      <thead>
        <tr className="border-b border-line text-xs text-fg-subtle">
          <th scope="col" className="py-1.5 text-left font-medium">
            Nhóm tri thức
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Tổng
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Đã kiểm chứng
          </th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {rows.map(([name, count]) => (
          <tr key={name}>
            <th scope="row" className="py-2 text-left font-normal">
              {name}
            </th>
            <td className="py-2 text-right">{count.total}</td>
            <td className="py-2 text-right">{count.verified}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Stats() {
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchKnowledgeStats()
      .then(setStats)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  if (error) return <p role="alert">{error}</p>;
  if (!stats) return <p role="status">Đang tải số liệu…</p>;
  return (
    <div className="space-y-5">
      <Rows
        rows={[
          ["Hành vi gốc", stats.acts],
          ["Tình tiết giảm nhẹ", stats.circumstances.mitigating],
          ["Tình tiết tăng nặng", stats.circumstances.aggravating],
        ]}
      />
      <Rows
        rows={[
          ...Object.entries(stats.rules).map(
            ([name, count]): [string, VerifiedCount] => [RULE_FILES[name] ?? name, count],
          ),
          ["Tổng số luật", stats.rules_total],
        ]}
      />
      <p className="text-[13px] text-fg-muted">
        Luật phân loại sinh tự động được tạo bằng script từ dữ liệu vi phạm của NĐ 168/2024. Cột
        “Đã kiểm chứng” đếm theo cờ verified trong các file tri thức.
      </p>
    </div>
  );
}

export function KnowledgeDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Sheet open={open} onClose={onClose} side="center" label="Cơ sở tri thức">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="font-semibold">Cơ sở tri thức</h2>
        <IconButton label="Đóng" onClick={onClose}>
          <X size={18} aria-hidden />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <Stats />
      </div>
    </Sheet>
  );
}
