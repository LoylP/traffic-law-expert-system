import { Split } from "lucide-react";

import { ViolationCard } from "@/components/expert/ViolationCard";
import type { ConsultBranch } from "@/types/chat";

type BranchListProps = { branches: ConsultBranch[]; dependsOn: string[] };

/** Possible outcomes while some facts stay unknown: no fine is chosen for the user. */
export function BranchList({ branches, dependsOn }: BranchListProps) {
  return (
    <section aria-label="Các khả năng" className="space-y-3">
      <h2 className="flex items-center gap-2 pt-1 text-sm font-semibold text-fg-muted">
        <Split size={16} aria-hidden />
        {branches.length} khả năng, phụ thuộc vào {dependsOn.join(", ")}
      </h2>
      {branches.map((branch, index) => (
        <div key={index} className="space-y-2 border-l-3 border-warn-line pl-3">
          <p className="text-sm font-medium">
            Nếu{" "}
            {branch.conditions
              .map((c) => `${c.slot_label}: ${c.labels.join(" hoặc ")}`)
              .join("; ")}
          </p>
          {branch.violations.map((violation) => (
            <ViolationCard key={violation.citation_id} violation={violation} />
          ))}
        </div>
      ))}
    </section>
  );
}
