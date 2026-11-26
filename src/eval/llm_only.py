"""Baseline `llm_only`: retrieval + LLM, no rule engine (DESIGN §11).

This is the only place where an LLM is asked to decide violations and fines. It
exists to be compared with the expert system and is never used by the product.
"""

from __future__ import annotations

import json
from typing import Any

from src.reasoning.grounder import Retriever

TOP_K = 10
STATUSES = ("answered", "need_info", "unknown")
SANCTION_TYPES = ("revoke_license", "confiscate", "remedy")

SYSTEM_PROMPT = """Bạn tư vấn xử phạt vi phạm giao thông đường bộ Việt Nam (NĐ 168/2024/NĐ-CP, \
áp dụng từ 01/01/2025). Dựa vào mô tả của người dùng và danh sách điều khoản được truy hồi, \
trả về DUY NHẤT một đối tượng JSON:
- status: "answered" nếu đủ căn cứ kết luận; "need_info" nếu thiếu dữ kiện làm thay đổi điều \
khoản áp dụng (loại phương tiện, mức nồng độ cồn, mức vượt tốc độ...); "unknown" nếu không đủ \
căn cứ hoặc ngoài phạm vi.
- violations: danh sách citation_id của các điều khoản bị vi phạm, chỉ lấy từ danh sách.
- recommended_fine_total: tổng tiền phạt đề xuất (đồng). Mỗi hành vi lấy mức trung bình của \
khung; có tình tiết tăng nặng thì cao hơn, giảm nhẹ thì thấp hơn; tổ chức phạt gấp đôi cá nhân.
- points_deducted_total: số điểm giấy phép lái xe bị trừ; nhiều hành vi thì lấy mức trừ lớn \
nhất, không cộng dồn.
- sanctions: loại hình phạt bổ sung (revoke_license, confiscate, remedy).
Khi status không phải "answered" và chưa xác định được hành vi nào thì violations = [] và các \
con số bằng 0."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "violations": {"type": "array", "items": {"type": "string"}},
        "recommended_fine_total": {"type": "integer"},
        "points_deducted_total": {"type": "integer"},
        "sanctions": {"type": "array", "items": {"type": "string", "enum": list(SANCTION_TYPES)}},
    },
    "required": [
        "status",
        "violations",
        "recommended_fine_total",
        "points_deducted_total",
        "sanctions",
    ],
    "additionalProperties": False,
}


def validate_output(data: dict[str, Any]) -> None:
    if data.get("status") not in STATUSES:
        raise ValueError(f"status phải thuộc {STATUSES}")
    for name in ("violations", "sanctions"):
        value = data.get(name)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{name} phải là danh sách chuỗi")
    for name in ("recommended_fine_total", "points_deducted_total"):
        value = data.get(name)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} phải là số nguyên")


def format_candidates(results: list[dict[str, Any]]) -> str:
    fields = (
        "citation_id",
        "vehicle_class",
        "description",
        "fine_min",
        "fine_max",
        "points_deducted",
        "sanctions",
    )
    return "\n".join(
        json.dumps({k: r["raw_node"].get(k) for k in fields}, ensure_ascii=False) for r in results
    )


class LLMOnlyBaseline:
    """One conversation per case: `ask` for the query, then once per follow-up."""

    def __init__(self, retriever: Retriever, client: Any, top_k: int = TOP_K):
        self.retriever = retriever
        self.client = client
        self.top_k = top_k
        self.reset()

    def reset(self) -> None:
        self.messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.user_texts: list[str] = []

    def retrieve(self, message: str) -> list[dict[str, Any]]:
        self.user_texts.append(message)
        return self.retriever.search(" ".join(self.user_texts), top_k=self.top_k)

    def ask(self, message: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Raises LLMError when no valid JSON comes back."""
        content = f"Người dùng: {message}\n\nĐiều khoản truy hồi:\n{format_candidates(results)}"
        self.messages.append({"role": "user", "content": content})
        data = self.client.chat_json(self.messages, SCHEMA, validator=validate_output)
        self.messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})
        return data
