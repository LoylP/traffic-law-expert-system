"""Rule-based FactExtractor: fallback when the LLM fails, and ablation baseline.

Vocabulary comes from the synonyms in acts.yaml / circumstances.yaml; numbers,
dates and context come from regular expressions. No network, no LLM.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from src.extract.vehicle_mapping import match_user_vehicles
from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.schema import ExtractionResult, Facts

NUMBER = r"\d+(?:[.,]\d+)?"
SPEED_UNIT = r"\s*(?:km\s*/\s*(?:h|giờ)|kmh|km|cây số)"

# "đi ngược chiều" also covers "đi xe máy ngược chiều": the vehicle may follow the verb.
_DRIVE_VERBS = ("đi", "chạy", "lái")
_VEHICLE_GAP = r"(?:\s+(?:xe|ô tô|mô tô)(?:\s+(?!không|chưa|chẳng)\w+){0,2}?)?"
_NEGATION = re.compile(r"(?<!\w)(?:không|chưa|chẳng|chả)(?:\s+(?:hề|có|bị))?\s*$")

# A synonym of these also describes other people ("tông người già"), so it only
# counts when the speaker says it about the violator.
_SELF_ONLY_CIRCUMSTANCES = {"CIR_PREGNANT_ELDERLY_DISABLED"}
_SELF_REFERENCE = re.compile(
    r"(?<!\w)(?:tôi|mình|em|người vi phạm|người lái|tài xế)\s+(?:là\s+|đang\s+(?:là\s+)?)?$"
)

_RESISTANCE_PATTERNS = {
    "RES_FLEE": r"bỏ chạy|bỏ trốn|tăng ga(?:\s+\w+){0,2}\s+(?:chạy|trốn)|phóng xe chạy|chạy trốn",
    "RES_OBSTRUCT": r"chống đối|cản trở",
    "RES_INSULT_OFFICER": (
        r"(?:lăng mạ|chửi(?: bới| mắng)?|phỉ báng|xúc phạm|thóa mạ)(?:\s+\w+){0,3}?\s+"
        r"(?:csgt|cảnh sát|công an|cán bộ|người thi hành công vụ)"
    ),
}
_OFFICER = r"(?:csgt|cảnh sát(?: giao thông)?|công an|người thi hành công vụ|người điều khiển giao thông)"
_OFFICER_SIGNAL = (
    rf"{_OFFICER}(?:\s+\w+){{0,3}}?\s+(?:ra hiệu(?: lệnh)?|yêu cầu(?: dừng)?|thổi còi|vẫy|bắt dừng|"
    r"chặn lại|dừng xe)|hiệu lệnh dừng(?: xe)?|yêu cầu dừng xe"
)
_ACCIDENT = r"gây(?: ra)?\s+tai nạn|tông (?:vào|trúng|phải)|đâm (?:vào|trúng)|va chạm gây"

_ROAD_PATTERNS = (
    ("ROAD_EXPRESSWAY", r"cao tốc"),
    ("ROAD_TUNNEL", r"hầm(?: đường bộ| chui)?(?!\w)"),
    ("ROAD_RESIDENTIAL", r"khu (?:vực )?(?:đông )?dân cư|khu đông dân"),
)
_TIME_PATTERNS = (
    ("TIME_NIGHT", r"ban đêm|buổi tối|tối qua|tối nay|đêm qua|đêm nay|nửa đêm|đêm khuya|lúc khuya|\d{1,2}\s*(?:h|giờ)\s*(?:đêm|tối)"),
    ("TIME_DAY", r"ban ngày|buổi sáng|sáng nay|buổi trưa|buổi chiều|giữa trưa"),
)
_ORGANIZATION = (
    r"^(?:một\s+|bên\s+)?(?:công ty|doanh nghiệp|hợp tác xã)"
    r"|(?<!\w)(?:công ty|doanh nghiệp|hợp tác xã)(?:\s+\w+){0,4}?\s+(?:vi phạm|điều khiển|bị phạt)"
    r"|(?:chủ thể|đối tượng vi phạm) là (?:một )?tổ chức"
)
_NUMBER_WORDS = {"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5, "sáu": 6}
_COUNT = r"(\d+|một|hai|ba|bốn|năm|sáu)(?!\w)"
DRANK_PATTERN = (
    r"(?:uống|nhậu|làm)(?:\s+\w+){0,2}?\s+(?:rượu|bia)|(?<!\w)nhậu(?!\w)|say xỉn|"
    r"uống (?:một )?(?:chút|ít|vài (?:ly|chén|lon|cốc))(?!\s+(?:nước|trà|cà phê|thuốc|sữa))|"
    r"có (?:nồng độ )?cồn|nồng độ cồn|thổi (?:ra )?cồn"
)


def normalize(text: str) -> str:
    """NFC + lowercase. Length-preserving for NFC input, so spans map back."""
    return unicodedata.normalize("NFC", text).lower()


def to_number(text: str) -> float:
    return float(text.replace(",", "."))


def parse_date(text: str) -> date | None:
    """dd/mm/yyyy (or -, .) and "ngày d tháng m năm yyyy"."""
    for pattern in (
        r"(?<!\d)(\d{1,2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*((?:19|20)\d{2})(?!\d)",
        r"(?<!\d)(\d{1,2})\.(\d{1,2})\.((?:19|20)\d{2})(?!\d)",
        r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+((?:19|20)\d{2})",
    ):
        found = re.search(pattern, normalize(text))
        if found:
            day, month, year = map(int, found.groups())
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def _phrase_pattern(phrase: str) -> str:
    verb, _, rest = phrase.partition(" ")
    if verb in _DRIVE_VERBS and rest:
        return rf"{verb}{_VEHICLE_GAP}\s+{re.escape(rest)}"
    return re.escape(phrase)


class RegexExtractor:
    name = "regex"

    def __init__(self, kb: KnowledgeBase | None = None):
        self.kb = kb or get_knowledge_base()
        entries = [
            (normalize(phrase), kind, item_id)
            for kind, items in (("acts", self.kb.acts), ("circumstances", self.kb.circumstances))
            for item_id, item in items.items()
            for phrase in item.get("synonyms") or []
        ]
        self._lexicon = sorted(entries, key=lambda e: len(e[0]), reverse=True)

    def extract(self, message: str) -> ExtractionResult:
        original = unicodedata.normalize("NFC", message)
        text = normalize(message)
        data: dict[str, Any] = {}
        evidence: dict[str, list[str]] = {}

        def span(start: int, end: int) -> str:
            return original[start:end] if len(original) == len(text) else text[start:end]

        def note(field: str, start: int, end: int) -> None:
            piece = span(start, end)
            if piece not in evidence.setdefault(field, []):
                evidence[field].append(piece)

        def search(field: str, pattern: str, negatable: bool = True) -> re.Match[str] | None:
            for found in re.finditer(pattern, text):
                if negatable and _NEGATION.search(text[: found.start()]):
                    continue
                note(field, found.start(), found.end())
                return found
            return None

        def add(field: str, item: str) -> None:
            values = data.setdefault(field, [])
            if item not in values:
                values.append(item)

        # -- vehicle ------------------------------------------------------
        vehicles = match_user_vehicles(text)
        if vehicles:
            vehicle_class, phrase = vehicles[0]
            data["vehicle_class"] = vehicle_class
            found = re.search(r"\s+".join(map(re.escape, phrase.split())), text)
            if found:
                note("vehicle_class", found.start(), found.end())

        # -- synonyms (longest first, matches never overlap) --------------
        taken: list[tuple[int, int]] = []
        for phrase, kind, item_id in self._lexicon:
            for found in re.finditer(rf"(?<!\w){_phrase_pattern(phrase)}(?!\w)", text):
                start, end = found.span()
                if any(start < b and a < end for a, b in taken):
                    continue
                taken.append((start, end))
                before = text[:start]
                if _NEGATION.search(before):
                    continue
                if item_id in _SELF_ONLY_CIRCUMSTANCES and not _SELF_REFERENCE.search(before):
                    continue
                add(kind, item_id)
                note(kind, start, end)

        self._speed(text, data, note)
        self._alcohol(text, data, search, add)

        # -- people -------------------------------------------------------
        found = search("passengers_count", rf"(?<!\w)kẹp\s+{_COUNT}")
        if found:  # "kẹp ba" counts the driver
            data["passengers_count"] = max(self._count(found.group(1)) - 1, 0)
        else:
            found = search("passengers_count", rf"(?<!\w)chở(?:\s+(?:theo|thêm|cùng))?\s+{_COUNT}\s*(?:người|bạn|đứa|em)")
            if found:
                data["passengers_count"] = self._count(found.group(1))

        acts = data.get("acts", [])
        if search("no_helmet_who", r"cả (?:hai|2)(?: người)?(?:\s+\w+){0,2}?\s+(?:không|chẳng) (?:đội )?(?:mũ|nón)", False):
            data["no_helmet_who"] = "both"
        elif "ACT_NO_HELMET" in acts and "ACT_PASSENGER_NO_HELMET" in acts:
            data["no_helmet_who"] = "both"
        elif "ACT_PASSENGER_NO_HELMET" in acts:
            data["no_helmet_who"] = "passenger"
        elif "ACT_NO_HELMET" in acts:
            data["no_helmet_who"] = "driver"

        # -- resistance, signal, consequence ------------------------------
        for resistance, pattern in _RESISTANCE_PATTERNS.items():
            if search("resistance", pattern):
                add("resistance", resistance)
        if search("officer_signal", _OFFICER_SIGNAL):
            data["officer_signal"] = True
        if search("consequence", _ACCIDENT):
            add("consequence", "CONS_ACCIDENT")

        # -- context, date, subject ---------------------------------------
        for field, patterns in (("road_type", _ROAD_PATTERNS), ("time_context", _TIME_PATTERNS)):
            for value, pattern in patterns:
                if search(field, pattern, False):
                    data[field] = value
                    break
        violation_date = parse_date(text)
        if violation_date:
            data["violation_date"] = violation_date
        if search("subject", _ORGANIZATION, False):
            data["subject"] = "SUBJ_ORGANIZATION"

        # Nothing recognised: hand the description to the OntologyGrounder.
        recognised = {"acts", "resistance", "consequence", "speed_over_kmh", "actual_speed_kmh",
                      "bac_blood_mg_100ml", "bac_breath_mg_l", "no_helmet_who", "passengers_count",
                      "drank_alcohol", "alcohol_test_refused"}
        if not recognised & set(data) and len(text.split()) >= 4:
            data["free_behaviors"] = [original.strip(" .?!")]

        data["evidence"] = {field: "; ".join(parts) for field, parts in evidence.items()}
        return ExtractionResult(facts=Facts.model_validate(data), source=self.name)

    @staticmethod
    def _count(token: str) -> int:
        return _NUMBER_WORDS.get(token) or int(token)

    @staticmethod
    def _speed(text: str, data: dict[str, Any], note) -> None:
        limit_cue = r"(?:giới hạn|cho phép|tối đa|biển(?: báo)?|quy định(?: là)?)"
        over_cue = r"(?:quá tốc độ|vượt tốc độ|vượt quá|chạy quá|lố tốc độ|quá|lố)"
        used: list[tuple[int, int]] = []

        def take(field: str, pattern: str) -> None:
            for found in re.finditer(pattern, text):
                start, end = found.span(1)
                if field in data or any(start < b and a < end for a, b in used):
                    continue
                used.append((start, end))
                data[field] = to_number(found.group(1))
                note(field, found.start(), found.end())

        take("speed_limit_kmh", rf"{limit_cue}[^\d.;]{{0,30}}?({NUMBER}){SPEED_UNIT}")
        take("speed_limit_kmh", rf"({NUMBER}){SPEED_UNIT}\s*(?:là\s+)?(?:giới hạn|cho phép)")
        take("speed_limit_kmh", rf"(?:đường|đoạn|khu vực|biển)\s+(?:giới hạn\s+)?({NUMBER})(?!\d|[.,]\d|\s*(?:mg|/|\.\d))\s*(?:km)?")
        take("speed_over_kmh", rf"{over_cue}(?:\s+(?:tốc độ|quy định|giới hạn|cho phép))*\s+(?:đến |tới |khoảng )?({NUMBER}){SPEED_UNIT}")
        take("actual_speed_kmh", rf"({NUMBER}){SPEED_UNIT}")
        take("actual_speed_kmh", rf"(?:chạy|phóng|tốc độ(?: thực tế)?(?: là)?)\s+({NUMBER})(?!\d|[.,]\d)(?!\s*(?:người|mg|tuổi))")
        if "speed_over_kmh" in data and "speed_limit_kmh" in data and "actual_speed_kmh" in data:
            del data["speed_over_kmh"]  # the derive rule computes it

    @staticmethod
    def _alcohol(text: str, data: dict[str, Any], search, add) -> None:
        mg = r"(?:mg|miligam)"
        blood = rf"({NUMBER})\s*{mg}\s*(?:/|trên)\s*100\s*(?:ml|mililít)(?:\s*máu)?"
        breath = rf"({NUMBER})\s*{mg}\s*(?:/|trên)\s*(?:1\s*)?(?:l|lít)(?!\w)(?:\s*khí thở)?"
        found = search("bac_blood_mg_100ml", blood, False)
        if found:
            data["bac_blood_mg_100ml"] = to_number(found.group(1))
        found = search("bac_breath_mg_l", breath, False)
        if found:
            data["bac_breath_mg_l"] = to_number(found.group(1))

        measured = any(data.get(f, 0) > 0 for f in ("bac_blood_mg_100ml", "bac_breath_mg_l"))
        # "từ chối thổi nồng độ cồn": mentions alcohol but is a refusal.
        if search(
            "acts",
            r"(?:từ chối|không chịu|không chấp hành(?: yêu cầu)?)(?:\s+(?!uống)\w+){0,3}?\s+"
            r"(?:thổi|đo|kiểm tra)(?:\s+\w+){0,3}?\s+cồn",
            False,
        ):
            add("acts", "ACT_REFUSE_ALCOHOL_TEST")
        refused = "ACT_REFUSE_ALCOHOL_TEST" in data.get("acts", [])
        if refused:
            if "ACT_ALCOHOL" in data.get("acts", []) and not measured:
                data["acts"].remove("ACT_ALCOHOL")
            # The refusal wording alone does not say the person drank.
            drank = re.search(r"(?<!không )(?:uống|nhậu|say xỉn)", text)
            if drank:
                note("drank_alcohol", drank.start(), drank.end())
        else:
            drank = search("drank_alcohol", DRANK_PATTERN)
        if drank:
            data["drank_alcohol"] = True
