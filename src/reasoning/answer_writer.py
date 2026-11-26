"""AnswerWriter (DESIGN §8): rephrases the decided result. It never decides.

The LLM text is accepted only if every amount, article, point deduction and
duration it mentions already exists in the payload; otherwise the Vietnamese
template is used.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.reasoning.llm_client import LLMClient, LLMError
from src.reasoning.penalty import format_money
from src.reasoning.schema import ConsultResult, PenaltySummary, Sanction

logger = logging.getLogger(__name__)

MAX_WORDS = 150
DESCRIPTION_LIMIT = 220
UNKNOWN_TEXT = (
    "Không đủ căn cứ để xác định hành vi vi phạm từ mô tả này. "
    "Bạn hãy nêu rõ loại phương tiện và hành vi cụ thể."
)
OUT_OF_SCOPE_TEXT = "Trường hợp này nằm ngoài phạm vi xử lý của hệ thống."
DISCLAIMER = "Mức đề xuất chỉ mang tính tham khảo; người có thẩm quyền quyết định mức phạt."
SANCTION_LABELS = {
    "revoke_license": "tước quyền sử dụng giấy phép lái xe",
    "confiscate": "tịch thu",
    "remedy": "buộc khắc phục hậu quả",
}

SYSTEM_PROMPT = f"""Bạn viết câu trả lời tiếng Việt cho người hỏi về xử phạt giao thông.
Dữ liệu JSON dưới đây là kết quả ĐÃ được hệ chuyên gia quyết định.
- Chỉ diễn đạt lại dữ liệu trong JSON, tối đa {MAX_WORDS} từ, không dùng markdown.
- Đây là mức ĐỀ XUẤT tham khảo, chưa phải quyết định xử phạt: không viết "bạn đã bị xử phạt".
- Với mỗi hành vi, nêu căn cứ đúng như trường label và mức đề xuất của hành vi đó.
- KHÔNG thêm điều luật, khoản, số tiền, số điểm, số tháng hay hình thức phạt không có trong JSON.
- KHÔNG tự cộng, trừ hay làm tròn số. Viết số tiền bằng chữ số, ví dụ "5.000.000 đồng".
- Số điểm giấy phép lái xe bị trừ là total_points_deducted, không cộng dồn."""

_GROUPED = r"\d{1,3}(?:\.\d{3})+"
_AMOUNT = rf"(?:{_GROUPED}|\d+(?:,\d+)?)"
_UNITS = {"tỷ": 10**9, "triệu": 10**6, "nghìn": 10**3, "ngàn": 10**3, "đồng": 1, "vnđ": 1, "vnd": 1, "đ": 1}
_UNIT = r"(tỷ|triệu|nghìn|ngàn|đồng|vnđ|vnd|đ)(?!\w)"
_MONEY_RANGE = re.compile(rf"({_AMOUNT})\s*(?:đến|tới|-|–)\s*{_AMOUNT}\s*(tỷ|triệu|nghìn|ngàn)(?!\w)")
_MONEY = re.compile(rf"({_AMOUNT})\s*{_UNIT}")
_BARE_GROUPED = re.compile(rf"(?<![\d.,])({_GROUPED})(?![\d.,]*\d)(?!\s*(?:tỷ|triệu|nghìn|ngàn))")
_SPELLED_MONEY = re.compile(
    r"(?<!\w)(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|mươi|trăm|vài)\s+(?:tỷ|triệu|nghìn|ngàn)(?!\w)"
)
# Forms of penalty the text may only mention when the payload has them.
_SANCTION_TERMS = ("cảnh cáo", "tước", "tịch thu", "tạm giữ", "đình chỉ", "phạt tù", "khắc phục")
_ARTICLE = re.compile(r"(?<!\w)điều\s+(\d+)")
_CLAUSE = re.compile(r"(?<!\w)khoản\s+(\d+)")
_POINTS = re.compile(r"(\d+)\s*điểm|trừ\s+(\d+)(?![\d.,])(?!\s*(?:triệu|nghìn|đồng|tháng))")
_MONTHS = re.compile(r"(\d+)\s*(?:(?:đến|tới|-|–)\s*(\d+)\s*)?tháng")


def _value(amount: str, unit: str = "đồng") -> int:
    if re.fullmatch(_GROUPED, amount):
        number = float(amount.replace(".", ""))
    else:
        number = float(amount.replace(",", "."))
    return round(number * _UNITS[unit])


def money_values(text: str) -> set[int]:
    text = text.lower()
    values = {_value(m.group(1), m.group(2)) for m in _MONEY_RANGE.finditer(text)}
    values |= {_value(m.group(1), m.group(2)) for m in _MONEY.finditer(text)}
    values |= {_value(m.group(1)) for m in _BARE_GROUPED.finditer(text)}
    return values


def _numbers(pattern: re.Pattern[str], text: str) -> set[int]:
    return {int(g) for m in pattern.finditer(text.lower()) for g in m.groups() if g}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    return []


def check_answer(text: str, payload: dict[str, Any]) -> list[str]:
    """Reasons to reject the LLM answer (empty = accepted)."""
    source = "\n".join(_strings(payload))
    amounts = money_values(source)
    points = _numbers(_POINTS, source) | {payload.get("total_points_deducted") or 0}
    months = _numbers(_MONTHS, source)
    amounts.add(payload.get("total_recommended_fine") or 0)
    for item in payload.get("violations", []):
        amounts.update(item.get("fine_range") or [])
        amounts.add(item.get("recommended_fine") or 0)
        points.add(item.get("points_deducted") or 0)
        for sanction in item.get("sanctions", []):
            months.update(
                v for v in (sanction.get("duration_min"), sanction.get("duration_max")) if v is not None
            )

    sanctions_text = " ".join(
        [source]
        + [
            SANCTION_LABELS.get(s.get("type"), "")
            for item in payload.get("violations", [])
            for s in item.get("sanctions", [])
        ]
    ).lower()

    problems = []
    invented = [t for t in _SANCTION_TERMS if t in text.lower() and t not in sanctions_text]
    if invented:
        problems.append(f"hình thức xử phạt không có trong dữ liệu: {invented}")
    if not text.strip():
        problems.append("câu trả lời rỗng")
    if len(text.split()) > MAX_WORDS:
        problems.append(f"dài hơn {MAX_WORDS} từ")
    if _SPELLED_MONEY.search(text.lower()):
        problems.append("số tiền viết bằng chữ nên không kiểm chứng được")
    for label, found, allowed in (
        ("số tiền", money_values(text), amounts),
        ("Điều", _numbers(_ARTICLE, text), _numbers(_ARTICLE, source)),
        ("khoản", _numbers(_CLAUSE, text), _numbers(_CLAUSE, source)),
        ("điểm bị trừ", _numbers(_POINTS, text), points),
        ("số tháng", _numbers(_MONTHS, text), months),
    ):
        if found - allowed:
            problems.append(f"{label} không có trong dữ liệu: {sorted(found - allowed)}")
    return problems


def sanction_text(sanction: Sanction) -> str:
    text = SANCTION_LABELS.get(sanction.type, sanction.type)
    if sanction.duration_min is not None:
        text += f" từ {sanction.duration_min} đến {sanction.duration_max} tháng"
    return text


def _shorten(text: str) -> str:
    text = text.rstrip(" ;.")
    if len(text) <= DESCRIPTION_LIMIT:
        return text
    return text[:DESCRIPTION_LIMIT].rsplit(" ", 1)[0] + "…"


class AnswerWriter:
    def __init__(self, client: LLMClient | None = None):
        self.client = client  # None = template only

    @staticmethod
    def payload(result: ConsultResult, penalty: PenaltySummary) -> dict[str, Any]:
        return {
            "status": result.status,
            "violations": [
                v.model_dump(mode="json", exclude={"citation_id", "legal_text"})
                for v in result.violations
            ],
            "total_recommended_fine": result.total_recommended_fine,
            "total_recommended_fine_text": format_money(result.total_recommended_fine),
            "total_points_deducted": penalty.total_points_deducted,
        }

    def write(
        self,
        result: ConsultResult,
        penalty: PenaltySummary,
        remarks: list[str] | None = None,
        use_llm: bool = True,
    ) -> tuple[str, str]:
        """Return (answer text, "llm" | "template").

        `remarks` (engine message, notes, warnings) are appended verbatim so the
        LLM can neither drop nor alter them. Only decided answers go to the LLM.
        """
        remarks = list(remarks or [])
        if use_llm and self.client and result.status == "answered":
            payload = self.payload(result, penalty)
            try:
                text = self.client.chat_text(
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ]
                )
            except LLMError as error:
                logger.warning("AnswerWriter LLM failed: %s", error)
            else:
                problems = check_answer(text, payload)
                if not problems:
                    return "\n".join([text.strip(), *remarks, DISCLAIMER]), "llm"
                logger.warning("AnswerWriter output rejected: %s", "; ".join(problems))
        return self.template(result, penalty, remarks), "template"

    @staticmethod
    def template(result: ConsultResult, penalty: PenaltySummary, remarks: list[str]) -> str:
        lines: list[str] = []
        if result.status == "unknown":
            lines.append(UNKNOWN_TEXT)
        elif result.status == "out_of_scope":
            lines.append(OUT_OF_SCOPE_TEXT)
        elif result.status == "need_info":
            lines.append("Cần bổ sung thông tin để kết luận đầy đủ:")
            lines += [f"- {q.text}" for q in result.questions]

        if result.violations:
            if result.status == "need_info":
                lines.append("Các hành vi đã xác định được (kết quả tạm thời):")
            else:
                lines.append(f"Xác định {len(result.violations)} hành vi vi phạm:")
            for item in result.violations:
                line = f"- {item.label}: {_shorten(item.description)}."
                if item.fine_range:
                    low, high = item.fine_range
                    line += (
                        f" Khung phạt {format_money(low)} – {format_money(high)}, "
                        f"mức đề xuất {format_money(item.recommended_fine)}."
                    )
                if item.points_deducted:
                    line += f" Điểm giấy phép lái xe bị trừ theo quy định: {item.points_deducted}."
                if item.sanctions:
                    line += f" Hình thức bổ sung: {'; '.join(map(sanction_text, item.sanctions))}."
                lines.append(line)
            lines.append(f"Tổng tiền phạt đề xuất: {format_money(result.total_recommended_fine)}.")
            if penalty.total_points_deducted:
                lines.append(
                    f"Tổng số điểm giấy phép lái xe bị trừ: {penalty.total_points_deducted} "
                    "(không cộng dồn giữa các hành vi)."
                )
        lines += remarks
        if result.violations:
            lines.append(DISCLAIMER)
        return "\n".join(lines)
