"use client";

import clsx from "clsx";

import { factGroup } from "@/components/expert/EvidenceHighlight";
import { fieldLabel, useLabels } from "@/lib/labels";
import type { FactUsed } from "@/types/chat";

export function FactTable({ facts }: { facts: FactUsed[] }) {
  const { valueLabel } = useLabels();
  if (facts.length === 0) {
    return <p className="text-sm text-fg-muted">Chưa trích xuất được dữ kiện nào.</p>;
  }
  return (
    <table className="w-full text-left text-[13px]">
      <thead className="sr-only">
        <tr>
          <th scope="col">Dữ kiện</th>
          <th scope="col">Giá trị</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {facts.map((fact, index) => (
          <tr key={`${fact.field}-${index}`} className="align-top">
            <th scope="row" className="w-2/5 py-2 pr-3 font-medium text-fg-muted">
              <span
                aria-hidden
                className={clsx(
                  "mr-1.5 inline-block size-2.5 rounded-sm",
                  factGroup(fact.field).color,
                )}
              />
              {fieldLabel(fact.field)}
            </th>
            <td className="py-2 break-words tabular-nums">
              {valueLabel(fact.value, fact.field)}
              {fact.origin === "derived" && (
                <span className="block text-xs text-fg-subtle">suy ra từ {fact.derived_from}</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
