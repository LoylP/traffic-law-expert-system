"""Check evaluation case files (DESIGN §11).

    python scripts/validate_cases.py [files...]   # default: test_cases(.draft).jsonl
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.eval import cases as C  # noqa: E402
from src.reasoning.knowledge_base import get_knowledge_base  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument(
        "--strict", action="store_true", help="group minimums are errors, not warnings"
    )
    args = parser.parse_args(argv)
    files = args.files or [p for p in (C.DRAFT_PATH, C.TEST_PATH) if p.exists()]
    if not files:
        print("Không có file case nào để kiểm tra.")
        return 1

    kb = get_knowledge_base()
    failed = False
    for path in files:
        try:
            items = C.load_cases(path)
        except (OSError, ValueError) as error:
            print(f"LỖI {error}")
            failed = True
            continue
        errors = C.validate_cases(items, kb)
        counts = Counter(c.get("group") for c in items)
        verified = sum(c.get("verified") is True for c in items)
        print(
            f"{path}: {len(items)} case, verified {verified}, "
            + ", ".join(f"{g}={counts.get(g, 0)}" for g in C.GROUPS)
        )
        shortfalls = C.group_shortfalls(items)
        if shortfalls and path.resolve() != C.SMOKE_PATH.resolve():
            missing = ", ".join(f"{g} thiếu {n}" for g, n in shortfalls.items())
            print(f"  CẢNH BÁO chưa đủ số case tối thiểu: {missing}")
            failed |= args.strict
        for error in errors:
            print(f"  LỖI {error}")
        failed |= bool(errors)
    print("KHÔNG ĐẠT" if failed else "ĐẠT")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
