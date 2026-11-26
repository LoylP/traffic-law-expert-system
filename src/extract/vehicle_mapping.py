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
