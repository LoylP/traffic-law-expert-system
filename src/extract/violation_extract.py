from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.extract.legal_corpus_builder import canonical_citation_id, make_citation_id
from src.extract.vehicle_mapping import (
    ARTICLE_TO_VEHICLE_168,
    match_vehicle,
    vehicle_for_article,
)

BASE_DIR = Path(__file__).resolve().parents[2]
PROCESSED_FILE = BASE_DIR / "data/processed/nghi_dinh_168.txt"
LAW_CORPUS_FILE = BASE_DIR / "data/structured/law_corpus.jsonl"
OUTPUT_FILE = BASE_DIR / "data/structured/violations_168_clean.json"
REPORT_FILE = BASE_DIR / "data/structured/extract_report.md"
LEGACY_FILE = Path("/tmp/legacy_violations.json")
SOURCE = "NĐ 168/2024/NĐ-CP"

ARTICLE_RE = re.compile(r"^\s*Điều\s+(\d+)\.?\s*(.*)$", re.IGNORECASE)
CLAUSE_RE = re.compile(r"^\s*(\d+)\.\s*(.*)$")
POINT_RE = re.compile(r"^\s*([a-zđ])\)\s*(.*)$", re.IGNORECASE)
MONEY_RANGE_RE = re.compile(
    r"từ\s+([\d.]+)\s*đồng\s+đến\s+([\d.]+)\s*đồng", re.IGNORECASE
)
POINT_REF_RE = re.compile(
    r"điểm\s+([a-zđ](?:\s*(?:,|;|và|hoặc)\s*(?:điểm\s+)?[a-zđ])*)\s+"
    r"khoản\s+(\d+)(?:\s+Điều\s+(\d+))?",
    re.IGNORECASE,
)
CLAUSE_REF_RE = re.compile(r"khoản\s+(\d+)(?:\s+Điều\s+(\d+))?", re.IGNORECASE)
# "trừ hành vi ... Điều này" / "(trừ trường hợp ...)": carve-outs, not sanction targets.
CARVE_OUT_RE = re.compile(
    r"\(\s*trừ\s[^()]*\)|"
    r"\btrừ\s+(?:các\s+)?(?:hành\s+vi|trường\s+hợp)[^;]*?"
    r"(?:Điều\s+(?:này|\d+(?:\s+của\s+Nghị\s+định\s+này)?)|(?=;)|$)",
    re.IGNORECASE,
)
# Counts produced before whole-clause references were resolved (kept for the report).
BASELINE_COUNTS = {"points_deducted": 143, "sanctions": 159}
# Condition attached to a point deduction, as worded in the deduction clause.
POINTS_CONDITION_RE = re.compile(
    r"\(\s*(trường\s+hợp[^()]*?)\s*\)|"
    r"\b(trong\s+trường\s+hợp\b.*?)(?=,?\s*(?:còn\s+)?bị\s+trừ\s+điểm)",
    re.IGNORECASE,
)


def extract_chapter_2(text: str) -> str:
    start = re.search(r"(?mi)^\s*Chương\s+II\b", text)
    if start is None:
        raise ValueError(f"Không tìm thấy Chương II trong {PROCESSED_FILE}")
    end = re.search(r"(?mi)^\s*Chương\s+III\b", text[start.end() :])
    return text[start.start() : start.end() + end.start()] if end else text[start.start() :]


def parse_structure(lines: list[str]) -> dict[int, dict[str, Any]]:
    tree: dict[int, dict[str, Any]] = {}
    article: dict[str, Any] | None = None
    clause: dict[str, Any] | None = None
    point: dict[str, str] | None = None

    def append_text(target: dict[str, Any], value: str) -> None:
        target["text"] = f"{target['text']} {value}".strip()

    for raw_line in lines:
        line = raw_line.strip()
        if not line or re.match(r"^Mục\s+\d+\b", line, re.IGNORECASE):
            continue

        article_match = ARTICLE_RE.match(line)
        if article_match:
            article_no = int(article_match.group(1))
            article = {"title": article_match.group(2).strip(), "clauses": {}}
            tree[article_no] = article
            clause = None
            point = None
            continue

        if article is None:
            continue

        clause_match = CLAUSE_RE.match(line)
        if clause_match:
            clause_no = clause_match.group(1)
            clause = {"text": clause_match.group(2).strip(), "points": {}}
            article["clauses"][clause_no] = clause
            point = None
            continue

        point_match = POINT_RE.match(line)
        if point_match and clause is not None:
            point_letter = point_match.group(1).lower()
            point = {"text": point_match.group(2).strip()}
            clause["points"][point_letter] = point
            continue

        if point is not None:
            append_text(point, line)
        elif clause is not None:
            append_text(clause, line)

    return tree


def _money_value(value: str) -> int:
    return int(value.replace(".", ""))


def extract_fines(text: str) -> tuple[int | None, int | None, int | None, int | None]:
    matches = list(MONEY_RANGE_RE.finditer(text))
    if not matches:
        return None, None, None, None

    org_match = None
    personal_match = matches[0]
    if len(matches) > 1 and re.search(
        r"đối với cá nhân.{0,180}đối với tổ chức", text, re.IGNORECASE
    ):
        personal_match, org_match = matches[0], matches[1]

    fine_min, fine_max = (
        _money_value(personal_match.group(1)),
        _money_value(personal_match.group(2)),
    )
    if org_match:
        org_min, org_max = _money_value(org_match.group(1)), _money_value(org_match.group(2))
        return fine_min, fine_max, org_min, org_max
    return fine_min, fine_max, None, None


def _citation(article: int, clause: str, point: str | None = None) -> str:
    return canonical_citation_id(make_citation_id("ND168", article, clause, point))


def _iter_references(
    text: str, default_article: int
) -> list[tuple[int, str, str | None]]:
    """(article, clause, point) references; point is None for a whole clause."""
    references: list[tuple[int, str, str | None]] = []
    covered: list[tuple[int, int]] = []
    for match in POINT_REF_RE.finditer(text):
        article = int(match.group(3) or default_article)
        clause = match.group(2)
        covered.append(match.span())
        group = re.sub(r"\b(?:điểm|và|hoặc)\b", " ", match.group(1), flags=re.IGNORECASE)
        for letter in re.findall(r"[a-zđ]", group, re.IGNORECASE):
            references.append((article, clause, letter.lower()))

    for match in CLAUSE_REF_RE.finditer(text):
        if any(start <= match.start() < end for start, end in covered):
            continue
        article = int(match.group(2) or default_article)
        references.append((article, match.group(1), None))
    return list(dict.fromkeys(references))


def _references(text: str, law_ids: set[str], default_article: int) -> list[str]:
    ids = (_citation(*ref) for ref in _iter_references(text, default_article))
    return list(dict.fromkeys(cid for cid in ids if cid in law_ids))


def _referenced_rows(
    text: str, rows: list[dict[str, Any]], default_article: int
) -> list[dict[str, Any]]:
    """Violations targeted by a supplementary clause. A whole-clause reference
    covers every violation of that clause (law_corpus has no clause-level unit
    when the clause is split into points, so we match on rows, not on IDs)."""
    refs = set(_iter_references(CARVE_OUT_RE.sub(" ", text), default_article))
    return [
        row
        for row in rows
        if (row["article"], row["clause"], None) in refs
        or (row["article"], row["clause"], row["point"]) in refs
    ]


def _points_condition(text: str) -> str:
    """Verbatim condition of a deduction sentence; the whole sentence if unmarked."""
    match = POINTS_CONDITION_RE.search(text)
    return next(value for value in match.groups() if value) if match else text


def _apply_points(row: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    """With several deduction levels, keep the lowest as the base value and list
    the higher ones with their condition, to be shown rather than auto-applied."""
    if not candidates:
        return
    base = min(item["points"] for item in candidates)
    row["points_deducted"] = base
    row["points_conditional"] = [item for item in candidates if item["points"] > base]


def _text_for_unit(unit: dict[str, Any]) -> str:
    return str(unit.get("text", ""))


def _parse_legacy_citation(record: dict[str, Any]) -> str | None:
    basis = str(record.get("legal_basis", ""))
    match = re.search(
        r"Điều\s+(\d+)\s+Khoản\s+(\d+)(?:\s+Điểm\s+([a-zđ]))?",
        basis,
        re.IGNORECASE,
    )
    if not match:
        return None
    article, clause, point = match.groups()
    return _citation(int(article), clause, point.lower() if point else None)


def _sanctions_for_clause(text: str) -> list[dict[str, Any]]:
    sanctions: list[dict[str, Any]] = []
    lowered = text.lower()
    if "tước quyền sử dụng giấy phép lái xe" in lowered or "tước giấy phép lái xe" in lowered:
        months = [
            int(value)
            for value in re.findall(r"(\d+)\s*tháng", lowered)
        ]
        sanction: dict[str, Any] = {"type": "revoke_license"}
        if months:
            sanction["duration_min"] = min(months)
            sanction["duration_max"] = max(months)
        sanctions.append(sanction)
    if "tịch thu" in lowered:
        sanctions.append({"type": "confiscate"})
    if "biện pháp khắc phục hậu quả" in lowered or re.search(r"\bbuộc\b", lowered):
        sanctions.append({"type": "remedy"})
    return sanctions


def _override_reason(clause_text: str, point_text: str | None, vehicle: str) -> str:
    """Explain which phrase made a violation differ from its article default."""
    for location, text in (("điểm", point_text), ("lời dẫn khoản", clause_text)):
        match = match_vehicle(text or "")
        if match and match[0] == vehicle:
            return f"Nội dung {location} nêu “{match[1]}”"
    return "Suy ra từ nội dung khoản + điểm"


def _vehicle_group_table(
    rows: list[dict[str, Any]],
    article_vehicles: dict[int, str],
    override_reasons: dict[str, str],
) -> list[str]:
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["article"], row["vehicle_class"]), []).append(row)

    lines = [
        "| Điều | Vehicle class | Class mặc định của Điều | Số vi phạm | override_reason |",
        "|---:|---|---|---:|---|",
    ]
    for (article_no, vehicle), members in sorted(groups.items()):
        reasons = Counter(
            override_reasons[row["citation_id"]]
            for row in members
            if row["citation_id"] in override_reasons
        )
        summary = "; ".join(f"{reason} ({count})" for reason, count in sorted(reasons.items()))
        lines.append(
            f"| {article_no} | {vehicle} | {article_vehicles[article_no]} "
            f"| {len(members)} | {summary or '—'} |"
        )
    lines.append(f"| **Tổng** | | | **{len(rows)}** | |")
    return lines


def _override_table(
    rows: list[dict[str, Any]],
    article_vehicles: dict[int, str],
    override_reasons: dict[str, str],
) -> list[str]:
    lines = [
        "| citation_id | Class mặc định | Vehicle class | override_reason |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['citation_id']} | {article_vehicles[row['article']]} "
        f"| {row['vehicle_class']} | {override_reasons[row['citation_id']]} |"
        for row in rows
        if row["citation_id"] in override_reasons
    )
    return lines


def build_violations(
    tree: dict[int, dict[str, Any]], law_rows: list[dict[str, Any]]
) -> tuple[
    list[dict[str, Any]], list[str], dict[int, str], dict[str, str], list[str]
]:
    law_by_id = {canonical_citation_id(row["citation_id"]): row for row in law_rows}
    law_ids = set(law_by_id)
    article_vehicles: dict[int, str] = {}
    rows: list[dict[str, Any]] = []
    unparsed: list[str] = []
    override_reasons: dict[str, str] = {}
    conditional_notes: list[str] = []

    for article_no, article_data in sorted(tree.items()):
        article_vehicles[article_no] = vehicle_for_article(article_no, article_data["title"])
        for clause_no, clause_data in article_data["clauses"].items():
            clause_text = clause_data["text"]
            if "phạt tiền" not in clause_text.lower():
                continue
            fines = extract_fines(clause_text)
            if fines[0] is None or fines[1] is None or fines[0] <= 0 or fines[1] <= 0:
                if "ngoài việc bị phạt tiền" not in clause_text.lower():
                    unparsed.append(
                        f"Điều {article_no} khoản {clause_no}: không trích được khung phạt ({clause_text[:180]})"
                    )
                continue
            point_items = clause_data["points"]
            candidates = point_items.items() if point_items else [(None, None)]
            for point_letter, point_data in candidates:
                point_text = point_data["text"] if point_data else None
                citation_id = _citation(article_no, clause_no, point_letter)
                if citation_id not in law_by_id:
                    raise AssertionError(f"Citation không có trong law_corpus: {citation_id}")
                unit = law_by_id[citation_id]
                description = re.sub(r"^[a-zđ]\)\s*", "", point_text or clause_text, flags=re.I).strip()
                description_full = " ".join(
                    value for value in (clause_text, description) if value
                )
                specific_text = f"{clause_text} {point_text or ''}".strip()
                accident = bool(
                    re.search(r"gây\s+tai\s+nạn\s+giao\s+thông", specific_text, re.IGNORECASE)
                )
                refers_to = _references(specific_text, law_ids, article_no) if accident else []
                excludes = _references(specific_text, law_ids, article_no) if "trừ các hành vi" in specific_text.lower() else []
                vehicle = article_vehicles[article_no]
                if article_no not in ARTICLE_TO_VEHICLE_168:
                    detected_vehicle = vehicle_for_article(-1, specific_text)
                    if detected_vehicle != "VEH_ANY" and detected_vehicle != vehicle:
                        vehicle = detected_vehicle
                        override_reasons[citation_id] = _override_reason(
                            clause_text, point_text, detected_vehicle
                        )

                rows.append(
                    {
                        "violation_id": f"V{len(rows) + 1:04d}",
                        "citation_id": citation_id,
                        "article": article_no,
                        "clause": str(clause_no),
                        "point": point_letter,
                        "description": description,
                        "description_full": description_full,
                        "vehicle_class": vehicle,
                        "fine_min": fines[0],
                        "fine_max": fines[1],
                        "fine_org_min": fines[2],
                        "fine_org_max": fines[3],
                        "points_deducted": 0,
                        "points_conditional": [],
                        "sanctions": [],
                        "consequence_accident": accident,
                        "refers_to": refers_to,
                        "excludes": excludes,
                        "legal_text": _text_for_unit(unit),
                        "source": SOURCE,
                    }
                )

    # Points and supplementary sanctions are stated only in non-fine clauses; in
    # fine clauses, words like "bắt buộc" or "chằng buộc" describe the violation.
    fine_clauses = {(row["article"], row["clause"]) for row in rows}
    deductions: dict[str, list[dict[str, Any]]] = {}
    for article_no, article_data in tree.items():
        for clause_no, clause_data in article_data["clauses"].items():
            if (article_no, str(clause_no)) in fine_clauses:
                continue
            source_texts: list[tuple[str | None, str]] = [(None, clause_data["text"])]
            source_texts.extend(
                (letter, point_data["text"])
                for letter, point_data in clause_data["points"].items()
            )
            for point_letter, text in source_texts:
                target_rows = _referenced_rows(text, rows, article_no)

                points_match = re.search(
                    r"(?:trừ\s+điểm\s+giấy\s+phép\s+lái\s+xe\b[^;]*?(\d+)\s+điểm|"
                    r"trừ\s+(\d+)\s+điểm\s+giấy\s+phép\s+lái\s+xe)",
                    text,
                    re.IGNORECASE,
                )
                if points_match:
                    points = int(next(value for value in points_match.groups() if value))
                    source = _citation(article_no, str(clause_no), point_letter)
                    if target_rows and source not in law_ids:
                        raise AssertionError(f"Citation không có trong law_corpus: {source}")
                    for row in target_rows:
                        deductions.setdefault(row["citation_id"], []).append(
                            {
                                "points": points,
                                "condition": _points_condition(text),
                                "source": source,
                            }
                        )

                sanctions = _sanctions_for_clause(CARVE_OUT_RE.sub(" ", text))
                for row in target_rows:
                    for sanction in sanctions:
                        if sanction not in row["sanctions"]:
                            row["sanctions"].append(sanction)

    for row in rows:
        _apply_points(row, deductions.get(row["citation_id"], []))
        if row["points_conditional"]:
            levels = "; ".join(
                f"{item['points']} điểm nếu “{item['condition']}” ({item['source']})"
                for item in row["points_conditional"]
            )
            base = next(
                item
                for item in deductions[row["citation_id"]]
                if item["points"] == row["points_deducted"]
            )
            conditional_notes.append(
                f"`{row['citation_id']}`: mức cơ bản {base['points']} điểm "
                f"({base['source']}, bản thân mức này gắn điều kiện “{base['condition']}”); "
                f"không tự áp: {levels}"
            )

    return rows, unparsed, article_vehicles, override_reasons, conditional_notes


def _comparison_report(rows: list[dict[str, Any]]) -> list[str]:
    if not LEGACY_FILE.exists():
        return ["Không có `/tmp/legacy_violations.json`; bỏ qua đối chiếu dữ liệu cũ."]

    with LEGACY_FILE.open(encoding="utf-8") as file:
        legacy = json.load(file)
    new_by_citation = {row["citation_id"]: row for row in rows}
    old_by_citation: dict[str, dict[str, Any]] = {}
    for record in legacy:
        citation_id = _parse_legacy_citation(record)
        if citation_id:
            old_by_citation[citation_id] = record

    overlap = set(new_by_citation) & set(old_by_citation)
    only_new = set(new_by_citation) - set(old_by_citation)
    only_old = set(old_by_citation) - set(new_by_citation)
    lines = [
        f"- Trùng citation_id: {len(overlap)}",
        f"- Chỉ có ở bản mới: {len(only_new)}",
        f"- Chỉ có ở bản cũ: {len(only_old)}",
        "- 20 cặp mức phạt lệch nhau tối đa:",
    ]
    differences = []
    for citation_id in sorted(overlap):
        current, previous = new_by_citation[citation_id], old_by_citation[citation_id]
        old_fine = (previous.get("fine_min"), previous.get("fine_max"))
        new_fine = (current.get("fine_min"), current.get("fine_max"))
        if old_fine != new_fine:
            differences.append(f"  - `{citation_id}`: cũ {old_fine}, mới {new_fine}")
    lines.extend(differences[:20] or ["  - Không có mức phạt lệch nhau."])
    return lines


def write_report(
    rows: list[dict[str, Any]],
    unparsed: list[str],
    article_vehicles: dict[int, str],
    override_reasons: dict[str, str],
    conditional_notes: list[str],
) -> None:
    by_vehicle = Counter(row["vehicle_class"] for row in rows)
    with_points = sum(row["points_deducted"] > 0 for row in rows)
    with_sanctions = sum(bool(row["sanctions"]) for row in rows)
    with_excludes = sum(bool(row["excludes"]) for row in rows)
    lines = [
        "# Báo cáo trích xuất vi phạm NĐ 168",
        "",
        f"- Tổng số vi phạm: {len(rows)}",
        f"- Có trừ điểm GPLX: {with_points}",
        f"- Có chế tài bổ sung/khắc phục: {with_sanctions}",
        f"- Có loại trừ: {with_excludes}",
        "",
        "## Trước và sau khi sửa gán dẫn chiếu nguyên khoản",
        "",
        "| Số violation có | Trước | Sau |",
        "|---|---:|---:|",
        f"| points_deducted > 0 | {BASELINE_COUNTS['points_deducted']} | {with_points} |",
        f"| sanctions | {BASELINE_COUNTS['sanctions']} | {with_sanctions} |",
        "",
        f"## Mức trừ điểm phụ thuộc điều kiện ({len(conditional_notes)})",
        "",
        "`points_deducted` giữ mức thấp nhất; mức cao hơn nằm trong `points_conditional` "
        "để hiển thị trong phần giải thích, không tự áp.",
        "",
        *([f"- {item}" for item in conditional_notes] or ["- Không có."]),
        "",
        "## Số vi phạm theo Điều và vehicle_class",
        "",
        *_vehicle_group_table(rows, article_vehicles, override_reasons),
    ]
    lines.extend(
        [
            "",
            "## Tổng theo vehicle_class",
            "",
            *[f"- {vehicle}: {count}" for vehicle, count in sorted(by_vehicle.items())],
            "",
            f"## Violation bị đổi vehicle_class so với mặc định của Điều ({len(override_reasons)})",
            "",
            *_override_table(rows, article_vehicles, override_reasons),
            "",
            "## Khoản không parse được mức phạt",
            "",
            *([f"- {item}" for item in unparsed] or ["- Không có."]),
            "",
            "## Đối chiếu bản legacy",
            "",
            *_comparison_report(rows),
            "",
        ]
    )
    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    text = PROCESSED_FILE.read_text(encoding="utf-8")
    tree = parse_structure(extract_chapter_2(text).splitlines())
    with LAW_CORPUS_FILE.open(encoding="utf-8") as file:
        law_rows = [json.loads(line) for line in file if line.strip()]

    violations, unparsed, article_vehicles, override_reasons, conditional_notes = (
        build_violations(tree, law_rows)
    )
    known_ids = {canonical_citation_id(row["citation_id"]) for row in law_rows}
    missing = [row["citation_id"] for row in violations if row["citation_id"] not in known_ids]
    if missing:
        raise AssertionError(f"Citation không tồn tại trong law_corpus: {missing[:20]}")

    OUTPUT_FILE.write_text(
        json.dumps(violations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(violations, unparsed, article_vehicles, override_reasons, conditional_notes)

    for article_no, vehicle in sorted(article_vehicles.items()):
        print(f"Điều {article_no}: {vehicle}")
    print(f"Đã trích xuất {len(violations)} vi phạm -> {OUTPUT_FILE}")
    print(f"Báo cáo: {REPORT_FILE}")


if __name__ == "__main__":
    main()
