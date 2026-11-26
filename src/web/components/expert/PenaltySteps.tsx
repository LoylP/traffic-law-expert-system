"use client";

import { useLabels } from "@/lib/labels";

// Amounts, point deductions and the net score.
const FIGURES = /(\d{1,3}(?:\.\d{3})+(?:\s*đồng)?|\d+\s*điểm(?= GPLX)|net = [+-]\d+|[AM] = \d+)/g;

function Highlighted({ text }: { text: string }) {
  // split() with a capture group puts the matches at the odd indexes.
  return text.split(FIGURES).map((part, index) =>
    index % 2 ? (
      <strong key={index} className="font-semibold text-accent tabular-nums">
        {part}
      </strong>
    ) : (
      part
    ),
  );
}

/** Group the "[citation] step" lines of PenaltyDecider under their violation. */
function groupSteps(lines: string[]) {
  const general: string[] = [];
  const perViolation = new Map<string, string[]>();
  for (const line of lines) {
    const match = /^\[([^\]]+)\]\s*(.*)$/.exec(line);
    if (!match) general.push(line);
    else perViolation.set(match[1], [...(perViolation.get(match[1]) ?? []), match[2]]);
  }
  const groups = [...perViolation].map(([title, steps]) => ({ title, steps }));
  if (general.length) {
    groups.push({ title: "Tình tiết và tổng hợp", steps: general });
  }
  return groups;
}

export function PenaltySteps({ lines }: { lines: string[] }) {
  const { humanize } = useLabels();
  if (lines.length === 0) {
    return <p className="text-sm text-fg-muted">Không có phép tính mức phạt.</p>;
  }
  return (
    <div className="space-y-4">
      {groupSteps(lines).map((group) => (
        <section key={group.title}>
          <h4 className="mb-1 text-sm font-semibold">{group.title}</h4>
          <ol className="list-decimal space-y-1 pl-5 text-[13px] break-words marker:text-fg-subtle">
            {group.steps.map((step, index) => (
              <li key={index}>
                <Highlighted text={humanize(step)} />
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
