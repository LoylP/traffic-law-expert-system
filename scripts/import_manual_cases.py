"""Append hand-written questions (data/eval/manual_cases.csv) to the draft.

Columns: group, query, vehicle, notes. Facts are only *suggested* by the
RegexExtractor and conclusions come from the engine on those facts (no grounder,
no LLM). Every row is `verified: false`: check it in the verify sheet.

    python scripts/import_manual_cases.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.eval import cases as C  # noqa: E402
from src.extract.vehicle_mapping import match_user_vehicles  # noqa: E402
from src.reasoning.extractor_regex import RegexExtractor  # noqa: E402
from src.reasoning.knowledge_base import get_knowledge_base  # noqa: E402
from src.reasoning.pipeline import parse_answer  # noqa: E402

VEHICLE_ANSWERS = {
    "VEH_CAR": "Ô tô",
    "VEH_MOTORBIKE": "Xe máy",
    "VEH_SPECIAL": "Xe máy chuyên dùng",
    "VEH_BICYCLE_RUDIMENTARY": "Xe đạp",
    "VEH_PEDESTRIAN": "Người đi bộ",
}


def vehicle_class_of(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if text.upper() in VEHICLE_ANSWERS:
        return text.upper()
    found = match_user_vehicles(text)
    if not found:
        raise ValueError(f"cột vehicle không nhận ra: {text!r}")
    return found[0][0]


def build_case(row: dict[str, str], case_id: str, extractor, concluder) -> dict:
    query = row["query"].strip()
    facts = C.compact_facts(extractor.extract(query).facts)
    vehicle = vehicle_class_of(row.get("vehicle") or "")
    turns, followups = [], []
    notes = [(row.get("notes") or "").strip()]
    if vehicle:
        if match_user_vehicles(query):
            facts["vehicle_class"] = vehicle
        else:
            # The query names no vehicle: the column is the reply if the system asks.
            first = concluder.ground_truth(facts)
            if first["first_ask_slot"] == "vehicle":
                answer = VEHICLE_ANSWERS[vehicle]
                turns.append(("vehicle", "vehicle_class", vehicle))
                followups.append({"expect_ask_slot": "vehicle", "answer": answer})
            else:
                notes.append(f"cột vehicle={vehicle} không dùng: câu không nêu và engine không hỏi")
    truth = concluder.ground_truth(facts, turns)
    case = {"id": case_id, "group": row["group"].strip().upper(), "source": "manual", "query": query}
    if followups:
        case["followups"] = followups
    case.update(ground_truth=truth, verified=False, notes="; ".join(n for n in notes if n))
    return case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=C.MANUAL_PATH)
    parser.add_argument("--draft", type=Path, default=C.DRAFT_PATH)
    args = parser.parse_args(argv)
    if not args.csv.exists():
        print(f"Không có {args.csv}. Xem data/eval/manual_cases.example.csv.")
        return 1

    kb = get_knowledge_base()
    extractor, concluder = RegexExtractor(kb), C.Concluder(kb)
    items = C.load_cases(args.draft) if args.draft.exists() else []
    queries = {c["query"] for c in items}
    ids = {c["id"] for c in items}
    added, number = [], 0
    with args.csv.open(encoding="utf-8-sig", newline="") as file:
        for line, row in enumerate(csv.DictReader(file), 2):
            query = (row.get("query") or "").strip()
            if not query or query in queries:
                continue
            group = (row.get("group") or "").strip().upper()
            if group not in C.GROUPS:
                print(f"{args.csv}:{line}: group không hợp lệ {group!r}")
                return 1
            number += 1
            while f"{group}-M{number:03d}" in ids:
                number += 1
            try:
                case = build_case(row, f"{group}-M{number:03d}", extractor, concluder)
            except ValueError as error:
                print(f"{args.csv}:{line}: {error}")
                return 1
            ids.add(case["id"])
            queries.add(query)
            added.append(case)

    C.save_cases(args.draft, items + added)
    print(f"Thêm {len(added)} case manual vào {args.draft} (tổng {len(items) + len(added)}).")
    for error in C.validate_cases(added, kb):
        print(f"  CẦN SỬA {error}")
    print("Facts chỉ là gợi ý của RegexExtractor: phải kiểm tra từng dòng trong verify sheet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
