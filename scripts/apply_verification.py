"""Checked verify sheet → data/eval/test_cases.jsonl (only rows with verified=true).

The sheet is the authority for `ground_truth`: nothing is recomputed. Queries and
follow-up replies come from the draft (edit them there).

    python scripts/apply_verification.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.export_verify_sheet import read_sheet, to_row  # noqa: E402
from src.eval import cases as C  # noqa: E402
from src.reasoning.knowledge_base import get_knowledge_base  # noqa: E402

TRUE_VALUES = {"true", "1", "x", "yes", "đúng"}


def parse_int(text: str) -> int:
    cleaned = (text or "").strip().replace(".", "").replace(",", "").replace(" ", "")
    return int(cleaned or 0)


def apply_row(case: dict, row: dict[str, str]) -> dict:
    cell = {name: (value or "").strip() for name, value in row.items() if name}
    truth = {
        "facts": C.decode_facts(cell["facts"]),
        "first_status": cell["first_status"],
        "first_ask_slot": cell["first_ask_slot"] or None,
        "status": cell["status"],
        "violations": sorted(C.decode_list(cell["violations"])),
        "recommended_fine_total": parse_int(cell["fine"]),
        "points_deducted_total": parse_int(cell["points"]),
        "sanctions": sorted(C.decode_list(cell["sanctions"])),
        "aggravating": sorted(C.decode_list(cell["aggravating"])),
        "mitigating": sorted(C.decode_list(cell["mitigating"])),
    }
    notes = [case.get("notes", ""), cell.get("reviewer_note", "")]
    group = cell.get("group") or case["group"]
    return {
        **case,
        "group": group,
        "ground_truth": truth,
        "verified": True,
        "notes": "; ".join(n for n in notes if n),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, default=C.DRAFT_PATH)
    parser.add_argument("--sheet", type=Path, default=C.VERIFY_PATH)
    parser.add_argument("--out", type=Path, default=C.TEST_PATH)
    args = parser.parse_args(argv)

    draft = {case["id"]: case for case in C.load_cases(args.draft)}
    errors, accepted, changed = [], [], 0
    for row in read_sheet(args.sheet):
        if (row.get("verified") or "").strip().lower() not in TRUE_VALUES:
            continue
        case = draft.get((row.get("id") or "").strip())
        if case is None:
            errors.append(f"{row.get('id')}: không có trong {args.draft.name}")
            continue
        try:
            updated = apply_row(case, row)
        except (KeyError, ValueError) as error:
            errors.append(f"{case['id']}: {error}")
            continue
        original = to_row(case)
        changed += any(
            (row.get(k) or "").strip() != original[k]
            for k in original
            if k not in ("query", "verified", "reviewer_note")
        )
        accepted.append(updated)

    errors += C.validate_cases(accepted, get_knowledge_base())
    if errors:
        print("\n".join(f"LỖI {e}" for e in errors))
        print(f"Chưa ghi {args.out}.")
        return 1
    if not accepted:
        print("Chưa có dòng nào verified=true.")
        return 1
    C.save_cases(args.out, accepted)
    counts = Counter(c["group"] for c in accepted)
    print(f"{args.out}: {len(accepted)} case ({dict(sorted(counts.items()))}), sửa {changed} dòng.")
    shortfalls = C.group_shortfalls(accepted)
    if shortfalls:
        print("CẢNH BÁO chưa đủ tối thiểu: " + ", ".join(f"{g} thiếu {n}" for g, n in shortfalls.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
