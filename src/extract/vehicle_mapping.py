from __future__ import annotations

import re
from typing import Optional

ARTICLE_TO_VEHICLE_168 = {
    6: "VEH_CAR",
    7: "VEH_MOTORBIKE",
    8: "VEH_SPECIAL",
    9: "VEH_BICYCLE_RUDIMENTARY",
    10: "VEH_PEDESTRIAN",
}


def detect_vehicle(text: str) -> Optional[str]:
    match = match_vehicle(text)
    return match[0] if match else None


def match_vehicle(text: str) -> Optional[tuple[str, str]]:
    """Return (vehicle_class, matched phrase) for the first matching pattern."""
    normalized = re.sub(r"\s+", " ", text.lower())
    patterns = (
        (r"(?<!\w)xe\s+máy\s+chuyên\s+dùng(?!\w)", "VEH_SPECIAL"),
        (r"(?<!\w)(?:mô\s+tô|gắn\s+máy|xe\s+máy)(?!\w)", "VEH_MOTORBIKE"),
        (r"(?<!\w)ô\s+tô(?!\w)", "VEH_CAR"),
        (r"(?<!\w)(?:xe\s+đạp|xe\s+thô\s+sơ)(?!\w)", "VEH_BICYCLE_RUDIMENTARY"),
        (r"(?<!\w)(?:người\s+đi\s+bộ|đi\s+bộ)(?!\w)", "VEH_PEDESTRIAN"),
        (r"(?<!\w)xe\s+cơ\s+giới(?!\w)", "VEH_MOTOR"),
    )
    for pattern, vehicle_class in patterns:
        found = re.search(pattern, normalized)
        if found:
            return vehicle_class, found.group(0)
    return None


# How users name a vehicle class explicitly, on top of the legal terms above.
# Generic wording ("xe", "chạy xe", "lái xe") deliberately matches nothing.
_USER_PATTERNS = (
    (r"(?<!\w)xe\s+máy\s+chuyên\s+dùng(?!\w)", "VEH_SPECIAL"),
    (r"(?<!\w)(?:mô\s+tô|gắn\s+máy|xe\s+máy)(?!\w)", "VEH_MOTORBIKE"),
    (r"(?<!\w)(?:ô[\s-]*tô|oto|xe\s+(?:tải|khách|buýt|hơi))(?!\w)", "VEH_CAR"),
    (r"(?<!\w)(?:xe\s+đạp|xe\s+thô\s+sơ)(?!\w)", "VEH_BICYCLE_RUDIMENTARY"),
    # "tông người đi bộ" names someone else, not the violator.
    (r"(?:^|(?<=là )|(?<!\w)(?:tôi|mình|em) )(?:người\s+)?đi\s+bộ(?!\w)", "VEH_PEDESTRIAN"),
    (r"(?<!\w)xe\s+cơ\s+giới(?!\w)", "VEH_MOTOR"),
)


def match_user_vehicles(text: str) -> list[tuple[str, str]]:
    """Every vehicle class a user names explicitly, as (class, phrase), in text order."""
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    found: list[tuple[int, int, str, str]] = []
    for pattern, vehicle_class in _USER_PATTERNS:
        for match in re.finditer(pattern, normalized):
            start, end = match.span()
            # The first pattern wins, so "xe máy chuyên dùng" is not also a motorbike.
            if not any(start < b and a < end for a, b, _, _ in found):
                found.append((start, end, vehicle_class, match.group(0)))
    return [(vehicle_class, phrase) for _, _, vehicle_class, phrase in sorted(found)]


def vehicle_for_article(article: int, title: str) -> str:
    mapped = ARTICLE_TO_VEHICLE_168.get(article)
    if mapped:
        return mapped

    classes = {
        vehicle_class
        for pattern, vehicle_class in (
            (r"(?<!\w)xe\s+máy\s+chuyên\s+dùng(?!\w)", "VEH_SPECIAL"),
            (r"(?<!\w)(?:mô\s+tô|gắn\s+máy)(?!\w)", "VEH_MOTORBIKE"),
            (r"(?<!\w)ô\s+tô(?!\w)", "VEH_CAR"),
            (r"(?<!\w)(?:xe\s+đạp|xe\s+thô\s+sơ)(?!\w)", "VEH_BICYCLE_RUDIMENTARY"),
            (r"(?<!\w)(?:người\s+đi\s+bộ|đi\s+bộ)(?!\w)", "VEH_PEDESTRIAN"),
            (r"(?<!\w)xe\s+cơ\s+giới(?!\w)", "VEH_MOTOR"),
        )
        if re.search(pattern, title.lower())
    }
    if len(classes) == 1:
        return classes.pop()
    return (detect_vehicle(title) or "VEH_ANY") if not classes else "VEH_ANY"
