"""Draft cases → data/eval/verify_cases.csv for manual checking.

Rows already in the sheet are kept untouched (your edits survive); only new case
ids are appended. `--force` rebuilds the sheet from the draft.

    python scripts/export_verify_sheet.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.eval import cases as C  # noqa: E402

COLUMNS = (
    "id", "group", "query", "facts", "first_status", "first_ask_slot", "status", "violations",
    "fine", "points", "sanctions", "aggravating", "mitigating", "verified", "reviewer_note",
)


def to_row(case: dict) -> dict[str, str]:
    truth = case["ground_truth"]
    query = case["query"]
    # Follow-up replies are shown for context; the query itself is not editable.
    for item in case.get("followups") or []:
        query += f" ⏎ [hỏi {item['expect_ask_slot']}] {item['answer']}"
    return {
        "id": case["id"],
        "group": case["group"],
        "query": query,
        "facts": C.encode_facts(truth["facts"]),
        "first_status": truth["first_status"],
        "first_ask_slot": truth["first_ask_slot"] or "",
        "status": truth["status"],
        "violations": C.encode_list(truth["violations"]),
        "fine": str(truth["recommended_fine_total"]),
        "points": str(truth["points_deducted_total"]),
        "sanctions": C.encode_list(truth["sanctions"]),
        "aggravating": C.encode_list(truth["aggravating"]),
        "mitigating": C.encode_list(truth["mitigating"]),
        "verified": "true" if case["verified"] else "false",
        "reviewer_note": "",
    }


def read_sheet(path: Path) -> list[dict[str, str]]:
    """Accepts the comma or semicolon delimiter a spreadsheet may save."""
    text = path.read_text(encoding="utf-8-sig")
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    return list(csv.DictReader(text.splitlines(keepends=True), delimiter=delimiter))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, default=C.DRAFT_PATH)
    parser.add_argument("--out", type=Path, default=C.VERIFY_PATH)
    parser.add_argument("--force", action="store_true", help="discard edits in the existing sheet")
    args = parser.parse_args(argv)

    kept = [] if args.force or not args.out.exists() else read_sheet(args.out)
    known = {row["id"] for row in kept}
    added = [to_row(case) for case in C.load_cases(args.draft) if case["id"] not in known]
    with args.out.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept + added)
    print(f"{args.out}: giữ {len(kept)} dòng, thêm {len(added)} dòng.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
