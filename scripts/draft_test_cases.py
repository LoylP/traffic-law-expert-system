"""Draft test cases (DESIGN §11) → data/eval/test_cases.draft.jsonl and smoke_cases.jsonl.

Queries and the facts the user states are written by hand below. Conclusions
(violations, fines, points...) are computed by InferenceEngine + PenaltyDecider
from those facts — never by the extraction pipeline. Every case is
`verified: false` until a human checks it (export_verify_sheet.py).

    python scripts/draft_test_cases.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.eval import cases as C  # noqa: E402
from src.reasoning.knowledge_base import get_knowledge_base  # noqa: E402

CAR, MOTO = "VEH_CAR", "VEH_MOTORBIKE"
BIKE, WALK = "VEH_BICYCLE_RUDIMENTARY", "VEH_PEDESTRIAN"
ORG = "SUBJ_ORGANIZATION"
ACCIDENT = ["CONS_ACCIDENT"]


def F(vehicle: str | None = None, *acts: str, **slots: Any) -> dict[str, Any]:
    """Facts the user states. Act names are given without the ACT_ prefix."""
    facts: dict[str, Any] = {}
    if vehicle:
        facts["vehicle_class"] = vehicle
    if acts:
        facts["acts"] = [f"ACT_{a}" for a in acts]
    facts.update(slots)
    return facts


def cir(*names: str) -> list[str]:
    return [f"CIR_{n}" for n in names]


def T(slot: str, answer: str, field: str, value: Any) -> tuple[str, str, str, Any]:
    """Follow-up turn: expected question slot, reply text, field and value it fills."""
    return slot, answer, field, value


def Q(query: str, facts: dict[str, Any], *turns, notes: str = "") -> dict[str, Any]:
    return {"query": query, "facts": facts, "turns": list(turns), "notes": notes}


HELMET = {"no_helmet_who": "driver"}

DRAFT: dict[str, list[dict[str, Any]]] = {
    # A — one behaviour, standard wording
    "A": [
        Q("Người điều khiển ô tô không chấp hành hiệu lệnh của đèn tín hiệu giao thông bị phạt thế nào?",
          F(CAR, "RED_LIGHT")),
        Q("Tôi đi xe máy vượt đèn đỏ thì bị phạt bao nhiêu?", F(MOTO, "RED_LIGHT")),
        Q("Lái ô tô mà trong hơi thở có nồng độ cồn 0,2 mg/l khí thở thì mức phạt là gì?",
          F(CAR, "ALCOHOL", bac_breath_mg_l=0.2)),
        Q("Điều khiển xe mô tô có nồng độ cồn 65 mg/100 ml máu bị xử phạt ra sao?",
          F(MOTO, "ALCOHOL", bac_blood_mg_100ml=65)),
        Q("Ô tô chạy quá tốc độ quy định 7 km/h thì bị phạt bao nhiêu tiền?",
          F(CAR, "SPEEDING", speed_over_kmh=7)),
        Q("Xe mô tô chạy quá tốc độ quy định 15 km/h bị xử phạt thế nào?",
          F(MOTO, "SPEEDING", speed_over_kmh=15)),
        Q("Người đi xe máy không đội mũ bảo hiểm bị phạt bao nhiêu?",
          F(MOTO, "NO_HELMET", **HELMET)),
        Q("Điều khiển ô tô đi ngược chiều trên đường cao tốc bị phạt thế nào?",
          F(CAR, "WRONG_WAY", road_type="ROAD_EXPRESSWAY"),
          notes="exclude: khoản 11 điểm đ loại khoản 9 điểm d"),
        Q("Xe máy đi ngược chiều của đường một chiều thì mức phạt là bao nhiêu?",
          F(MOTO, "WRONG_WAY")),
        Q("Ô tô đi không đúng làn đường quy định bị xử phạt như thế nào?", F(CAR, "WRONG_LANE")),
        Q("Người đang lái xe ô tô dùng tay cầm và sử dụng điện thoại thì bị phạt bao nhiêu?",
          F(CAR, "PHONE_WHILE_DRIVING")),
        Q("Người đi xe máy không chấp hành yêu cầu kiểm tra về nồng độ cồn bị phạt thế nào?",
          F(MOTO, "REFUSE_ALCOHOL_TEST", alcohol_test_refused=True)),
        Q("Người lái ô tô không thắt dây đai an toàn bị phạt bao nhiêu tiền?",
          F(CAR, "NO_SEATBELT")),
        # Driving licence, bicycle and pedestrian signals (appended: earlier ids stay stable)
        Q("Người điều khiển ô tô không có giấy phép lái xe thì bị phạt bao nhiêu?",
          F(CAR, "NO_LICENSE")),
        Q("Đi xe mô tô 150 phân khối nhưng bằng lái không đúng hạng thì bị phạt thế nào?",
          F(MOTO, "LICENSE_MISMATCH", engine_capacity_cc=150)),
        Q("Lái ô tô khi giấy phép lái xe đã hết hạn 3 tháng thì mức phạt là bao nhiêu?",
          F(CAR, "LICENSE_EXPIRED", license_expired_months=3)),
        Q("Tài xế ô tô kinh doanh vận tải không mang theo giấy phép lái xe bị phạt bao nhiêu?",
          F(CAR, "LICENSE_NOT_CARRIED", transport_use="TRANSPORT_COMMERCIAL")),
        Q("Người đi xe đạp không chấp hành hiệu lệnh của đèn tín hiệu giao thông bị phạt bao nhiêu?",
          F(BIKE, "RED_LIGHT")),
        Q("Người đi bộ vượt đèn đỏ thì bị xử phạt thế nào?", F(WALK, "RED_LIGHT")),
    ],
    # B — everyday wording, abbreviations, missing diacritics, indirect violations
    "B": [
        Q("hqua e chạy xe máy tới ngã tư đèn đỏ rồi mà vẫn phóng qua luôn, bị tuýt còi, giờ phạt nhiu v ạ",
          F(MOTO, "RED_LIGHT")),
        Q("nhậu 3 lon xong lái oto về, đo ra 0.35 mg/l khí thở, mức phạt sao ad",
          F(CAR, "ALCOHOL", drank_alcohol=True, bac_breath_mg_l=0.35)),
        Q("Tối đi đám cưới về, làm vài ly rượu rồi chạy xe gắn máy, thổi lên 0,52 miligam trên 1 lít khí thở.",
          F(MOTO, "ALCOHOL", drank_alcohol=True, bac_breath_mg_l=0.52)),
        Q("Đoạn đường cho chạy 60 mà tui phóng xe hơi 87 km/h, bị bắn tốc độ rồi, đóng bao nhiêu?",
          F(CAR, "SPEEDING", actual_speed_kmh=87, speed_limit_kmh=60)),
        Q("xe may chay 78km/h cho gioi han 50km/h phat bao nhieu",
          F(MOTO, "SPEEDING", actual_speed_kmh=78, speed_limit_kmh=50),
          notes="không dấu hoàn toàn"),
        Q("Mình đi xe máy kẹp ba đi học về, có bị gì không?",
          F(MOTO, "OVERLOAD_PASSENGER", passengers_count=2)),
        Q("Thằng bạn tôi chạy xe máy mà chở thêm 3 đứa nữa phía sau, vậy là bị phạt sao?",
          F(MOTO, "OVERLOAD_PASSENGER", passengers_count=3)),
        Q("Chạy xe máy, mấy chú CSGT vẫy gậy bắt dừng xe mà mình sợ quá rồ ga bỏ chạy luôn.",
          F(MOTO, officer_signal=True, resistance=["RES_FLEE"]),
          notes="gián tiếp: derive R-DER-RES-01"),
        Q("Tôi lái ô tô quẹt trúng một người đi đường rồi hoảng quá bỏ đi luôn không dừng lại.",
          F(CAR, "HIT_AND_RUN", consequence=ACCIDENT, resistance=["RES_FLEE"]),
          notes="gián tiếp: bỏ chạy sau tai nạn, không có hiệu lệnh dừng xe"),
        Q("đang cầm lái xe máy mà tay bấm điện thoại nhắn tin cho bồ, bị công an chụp lại",
          F(MOTO, "PHONE_WHILE_DRIVING")),
        Q("CSGT chặn xe hơi của tôi kêu thổi cồn, tôi nhất quyết không chịu thổi.",
          F(CAR, "REFUSE_ALCOHOL_TEST", alcohol_test_refused=True)),
        Q("Ra đầu ngõ mua đồ nên đầu trần chạy xe máy, không đội cái nón bảo hiểm nào, phạt nhiu?",
          F(MOTO, "NO_HELMET", **HELMET)),
        Q("Chở nhỏ em ngồi sau xe máy mà nó không chịu đội mũ bảo hiểm, tôi có bị phạt không?",
          F(MOTO, "PASSENGER_NO_HELMET", no_helmet_who="passenger")),
        Q("Lỡ quẹo nhầm vô đường một chiều bằng xe máy, thành ra chạy ngược lại dòng xe.",
          F(MOTO, "WRONG_WAY")),
        Q("Đang chạy ô tô mà không cài dây an toàn thì có sao không mọi người",
          F(CAR, "NO_SEATBELT")),
        Q("Xe nhà tôi là ô tô 4 chỗ, chở bà chị ngồi ghế phụ mà chị không thắt dây an toàn.",
          F(CAR, "PASSENGER_NO_SEATBELT")),
        Q("khong that day an toan khi lái thì phat the nao",
          F(None, "NO_SEATBELT"), notes="gián tiếp: suy ra ô tô từ dây an toàn (R-DER-VEH-01)"),
        Q("em chạy xe máy 110cc đi làm mà chưa thi bằng lái, bị công an giữ lại thì sao ạ",
          F(MOTO, "NO_LICENSE", engine_capacity_cc=110)),
    ],
    # C — several behaviours in one description
    "C": [
        Q("Tôi đi xe máy vượt đèn đỏ mà còn không đội mũ bảo hiểm.",
          F(MOTO, "RED_LIGHT", "NO_HELMET", **HELMET)),
        Q("xe máy kẹp 3, cả 3 đứa đều ko đội nón bảo hiểm, phạt hết bao nhiêu",
          F(MOTO, "OVERLOAD_PASSENGER", "NO_HELMET", "PASSENGER_NO_HELMET",
            passengers_count=2, no_helmet_who="both")),
        Q("Lái ô tô vừa nghe điện thoại cầm trên tay vừa vượt đèn đỏ.",
          F(CAR, "PHONE_WHILE_DRIVING", "RED_LIGHT")),
        Q("Chạy xe hơi trong khu dân cư giới hạn 50 km/h mà đi tới 66 km/h, lại còn không thắt dây an toàn.",
          F(CAR, "SPEEDING", "NO_SEATBELT", actual_speed_kmh=66, speed_limit_kmh=50,
            road_type="ROAD_RESIDENTIAL")),
        Q("Uống bia xong tôi chạy xe máy, đo được 0,18 mg/l, trên đường về còn vượt đèn đỏ và không đội mũ bảo hiểm.",
          F(MOTO, "ALCOHOL", "RED_LIGHT", "NO_HELMET", drank_alcohol=True,
            bac_breath_mg_l=0.18, **HELMET)),
        Q("Đêm qua đi ô tô ngược chiều đường một chiều, bị CSGT ra hiệu dừng xe thì tôi tăng ga bỏ chạy.",
          F(CAR, "WRONG_WAY", "IGNORE_OFFICER", officer_signal=True, resistance=["RES_FLEE"],
            time_context="TIME_NIGHT", road_type="ROAD_NORMAL"),
          T("road", "Đường khác", "road_type", "ROAD_NORMAL"),
          notes="nhiều lượt: cần loại đường để chọn khoản đi ngược chiều"),
        Q("Chạy xe máy lấn sang làn ô tô, vừa đi vừa cầm điện thoại xem bản đồ.",
          F(MOTO, "WRONG_LANE", "PHONE_WHILE_DRIVING")),
        Q("Tôi lái ô tô đi sai làn, chạy quá tốc độ cho phép 28 km/h và đang dùng điện thoại cầm tay.",
          F(CAR, "WRONG_LANE", "SPEEDING", "PHONE_WHILE_DRIVING", speed_over_kmh=28)),
        Q("Ô tô của tôi vượt đèn đỏ, CSGT thổi còi yêu cầu dừng nhưng tôi không dừng, kiểm tra nồng độ cồn tôi cũng từ chối.",
          F(CAR, "RED_LIGHT", "IGNORE_OFFICER", "REFUSE_ALCOHOL_TEST", officer_signal=True,
            alcohol_test_refused=True)),
        Q("Chiều nay em đi xe máy chở 2 bạn, bạn ngồi sau không đội mũ, em còn chạy quá 8 km/h nữa.",
          F(MOTO, "OVERLOAD_PASSENGER", "PASSENGER_NO_HELMET", "SPEEDING",
            passengers_count=2, no_helmet_who="passenger", speed_over_kmh=8,
            time_context="TIME_DAY")),
        Q("Kể chuyện hơi dài: sáng nay đi làm trễ, tôi lấy xe máy phóng đi mà quên đội mũ bảo hiểm, "
          "đến ngã tư thấy vắng nên vượt đèn đỏ, rồi chạy ngược chiều một đoạn đường một chiều cho nhanh.",
          F(MOTO, "NO_HELMET", "RED_LIGHT", "WRONG_WAY", time_context="TIME_DAY", **HELMET),
          notes="kể dài"),
        Q("Say rượu lái ô tô, nồng độ cồn 90 mg/100ml máu, đã vậy còn đi ngược chiều trên cao tốc.",
          F(CAR, "ALCOHOL", "WRONG_WAY", drank_alcohol=True, bac_blood_mg_100ml=90,
            road_type="ROAD_EXPRESSWAY")),
    ],
    # D — circumstances, consequences, organisations
    "D": [
        Q("Tôi lái ô tô chạy quá tốc độ 15 km/h và gây tai nạn giao thông.",
          F(CAR, "SPEEDING", speed_over_kmh=15, consequence=ACCIDENT),
          notes="escalate R-ESC-CAR-GEN"),
        Q("Xe máy của tôi chạy 72 km/h ở đoạn giới hạn 50, đâm vào xe phía trước gây tai nạn.",
          F(MOTO, "SPEEDING", actual_speed_kmh=72, speed_limit_kmh=50, consequence=ACCIDENT),
          notes="escalate R-ESC-MOTO-GEN"),
        Q("Ô tô vượt đèn đỏ gây tai nạn thì bị xử lý thế nào, tôi đã tự nguyện khắc phục hậu quả.",
          F(CAR, "RED_LIGHT", consequence=ACCIDENT, circumstances=cir("PREVENT_HARM")),
          notes="escalate R-ESC-CAR-LIGHT/REDLIGHT"),
        Q("Chạy xe máy đi ngược chiều đường một chiều rồi tông vào người ta gây tai nạn, đây là lần tái phạm.",
          F(MOTO, "WRONG_WAY", consequence=ACCIDENT, circumstances=cir("REPEAT")),
          notes="escalate R-ESC-MOTO-WRONGLANE-WAY-ACCIDENT"),
        Q("Công ty chúng tôi điều khiển xe ô tô vượt đèn đỏ thì tổ chức bị phạt bao nhiêu?",
          F(CAR, "RED_LIGHT", subject=ORG)),
        Q("Doanh nghiệp vi phạm: xe ô tô chạy quá tốc độ 25 km/h, vi phạm nhiều lần và có tổ chức.",
          F(CAR, "SPEEDING", speed_over_kmh=25, subject=ORG,
            circumstances=cir("MULTIPLE_TIMES", "ORGANIZED"))),
        Q("Tôi đi xe máy vượt đèn đỏ, đã tự nguyện khai báo và thành thật hối lỗi.",
          F(MOTO, "RED_LIGHT", circumstances=cir("VOLUNTARY_CONFESS"))),
        Q("Tôi đang mang thai, đi xe máy không đội mũ bảo hiểm, tôi thành thật hối lỗi và tự nguyện khai báo.",
          F(MOTO, "NO_HELMET", **HELMET,
            circumstances=cir("PREGNANT_ELDERLY_DISABLED", "VOLUNTARY_CONFESS"))),
        Q("Do bị người khác ép buộc nên tôi phải lái ô tô đi sai làn đường.",
          F(CAR, "WRONG_LANE", circumstances=cir("COERCED"))),
        Q("Bị người ta chặn đường chửi mắng làm tôi bị kích động, phóng ô tô quá tốc độ 12 km/h; nhà tôi hoàn cảnh đặc biệt khó khăn.",
          F(CAR, "SPEEDING", speed_over_kmh=12, circumstances=cir("PROVOKED", "HARDSHIP"))),
        Q("Tôi ở vùng sâu, trình độ lạc hậu, đi xe máy ngược chiều mà không biết là sai.",
          F(MOTO, "WRONG_WAY", circumstances=cir("BACKWARD"))),
        Q("Đi xe máy vượt đèn đỏ, CSGT yêu cầu dừng xe thì tôi chửi bới CSGT.",
          F(MOTO, "RED_LIGHT", officer_signal=True, resistance=["RES_INSULT_OFFICER"]),
          notes="gián tiếp: lăng mạ → tình tiết tăng nặng (R-DER-RES-03)"),
        Q("Tôi rủ rê, xúi giục trẻ em chạy xe máy vượt đèn đỏ cùng mình, bị yêu cầu dừng vi phạm mà vẫn tiếp tục.",
          F(MOTO, "RED_LIGHT", circumstances=cir("INCITE_MINOR", "CONTINUE_AFTER_STOP"))),
        Q("Một người lợi dụng chức vụ quyền hạn để lái ô tô đi ngược chiều đường một chiều, sau đó còn trốn tránh, che giấu vi phạm. Đoạn đường đó không phải cao tốc.",
          F(CAR, "WRONG_WAY", road_type="ROAD_NORMAL",
            circumstances=cir("ABUSE_POSITION", "CONCEAL"))),
        Q("Lợi dụng lúc đang có dịch bệnh, đường vắng, tôi chạy xe máy quá tốc độ 30 km/h trong thời gian đang chấp hành hình phạt.",
          F(MOTO, "SPEEDING", speed_over_kmh=30,
            circumstances=cir("EXPLOIT_DISASTER", "DURING_SENTENCE"))),
        Q("Vi phạm quy mô lớn, ảnh hưởng đến nhiều người và trẻ em: một đoàn xe ô tô vượt đèn đỏ, tôi là một người trong đó.",
          F(CAR, "RED_LIGHT", circumstances=cir("LARGE_SCALE", "MANY_VICTIMS"))),
        Q("Tôi sử dụng người bị tâm thần điều khiển xe máy vượt đèn đỏ.",
          F(MOTO, "RED_LIGHT", circumstances=cir("USE_MENTALLY_ILL"))),
        Q("Lái ô tô gây tai nạn khi đang dùng điện thoại, tôi đã ngăn chặn hậu quả nhưng đây là lần tái phạm.",
          F(CAR, "PHONE_WHILE_DRIVING", consequence=ACCIDENT,
            circumstances=cir("PREVENT_HARM", "REPEAT"))),
    ],
    # E — missing facts (need_info, some with follow-ups) and out of scope (unknown)
    "E": [
        Q("Vượt đèn đỏ phạt bao nhiêu?", F(None, "RED_LIGHT")),
        Q("vượt đèn đỏ bị sao",
          F(CAR, "RED_LIGHT"),
          T("vehicle", "Ô tô", "vehicle_class", CAR),
          notes="nhiều lượt: hỏi loại xe"),
        Q("Tôi uống rượu rồi chạy xe máy về nhà thì bị phạt bao nhiêu?",
          F(MOTO, "ALCOHOL", drank_alcohol=True, bac_breath_mg_l=0.3),
          T("alcohol", "0,3 mg/l", "bac_breath_mg_l", 0.3),
          notes="nhiều lượt: hỏi mức cồn, trả lời bằng số đo"),
        Q("Đi ô tô chạy quá tốc độ bị phạt thế nào?", F(CAR, "SPEEDING")),
        Q("xe máy chạy quá tốc độ trên đường giới hạn 40 km/h",
          F(MOTO, "SPEEDING", speed_limit_kmh=40, actual_speed_kmh=55),
          T("speed", "55 km/h", "actual_speed_kmh", 55),
          notes="nhiều lượt: chỉ thiếu tốc độ thực tế"),
        Q("Xe máy chở quá số người quy định thì phạt nhiêu?", F(MOTO, "OVERLOAD_PASSENGER")),
        Q("Lái xe sau khi nhậu bị xử phạt sao?",
          F(CAR, "ALCOHOL", drank_alcohol=True, alcohol_level="BAC_L2"),
          T("vehicle", "Ô tô", "vehicle_class", CAR),
          T("alcohol", "Trên 0,25 đến 0,4 mg/l", "alcohol_level", "BAC_L2"),
          notes="nhiều lượt: hỏi loại xe rồi mức cồn"),
        Q("Ngày 20/10/2024 tôi đi xe máy vượt đèn đỏ thì mức phạt là bao nhiêu?",
          F(MOTO, "RED_LIGHT", violation_date="2024-10-20"),
          notes="temporal: trước 01/01/2025"),
        Q("Xe máy chống đối, cản trở CSGT đang làm nhiệm vụ.",
          F(MOTO, "OBSTRUCT_OFFICER", resistance=["RES_OBSTRUCT"]),
          notes="ngoài phạm vi NĐ 168 (note R-NOTE-OBSTRUCT)"),
        Q("Thủ tục sang tên đổi chủ xe máy cần những giấy tờ gì?", F(MOTO),
          notes="ngoài phạm vi: thủ tục hành chính"),
        Q("Hôm nay trời mưa to quá, đường đi làm kẹt cứng.", F(),
          notes="ngoài phạm vi: không có hành vi"),
        Q("Tôi chạy xe máy mà không có bằng lái thì bị phạt bao nhiêu?",
          F(MOTO, "NO_LICENSE", engine_capacity_cc=150),
          T("license_class", "150 phân khối", "engine_capacity_cc", 150),
          notes="nhiều lượt: hỏi dung tích xe"),
        Q("Tôi đi xe máy, không kinh doanh vận tải, quên mang bằng lái thì phạt bao nhiêu?",
          F(MOTO, "LICENSE_NOT_CARRIED", transport_use="TRANSPORT_PRIVATE"),
          notes="Điều 18 chỉ phạt người kinh doanh vận tải; ghi chú dẫn Điều 48 khoản 3"),
    ],
}

# Ten cases to try the evaluation code (two per group, one multi-turn).
SMOKE: dict[str, list[dict[str, Any]]] = {
    "A": [
        Q("Xe ô tô vượt đèn đỏ bị phạt bao nhiêu?", F(CAR, "RED_LIGHT")),
        Q("Đi xe máy không đội mũ bảo hiểm phạt thế nào?", F(MOTO, "NO_HELMET", **HELMET)),
    ],
    "B": [
        Q("Chạy xe máy kẹp ba thì sao?", F(MOTO, "OVERLOAD_PASSENGER", passengers_count=2)),
        Q("Lái ô tô thổi ra 0,3 mg/l khí thở.", F(CAR, "ALCOHOL", bac_breath_mg_l=0.3)),
    ],
    "C": [
        Q("Đi xe máy vượt đèn đỏ, không đội mũ bảo hiểm.",
          F(MOTO, "RED_LIGHT", "NO_HELMET", **HELMET)),
        Q("Lái ô tô sử dụng điện thoại khi lái xe và đi sai làn.",
          F(CAR, "PHONE_WHILE_DRIVING", "WRONG_LANE")),
    ],
    "D": [
        Q("Ô tô chạy quá tốc độ 15 km/h gây tai nạn.",
          F(CAR, "SPEEDING", speed_over_kmh=15, consequence=ACCIDENT)),
        Q("Đi xe máy vượt đèn đỏ, tái phạm.", F(MOTO, "RED_LIGHT", circumstances=cir("REPEAT"))),
    ],
    "E": [
        Q("Vượt đèn đỏ bị phạt bao nhiêu?",
          F(MOTO, "RED_LIGHT"),
          T("vehicle", "Xe máy", "vehicle_class", MOTO),
          notes="nhiều lượt"),
        Q("Hôm nay trời đẹp quá.", F()),
    ],
}


def build(table: dict[str, list[dict[str, Any]]], concluder: C.Concluder, prefix: str = "") -> list:
    built = []
    for group, entries in table.items():
        for number, entry in enumerate(entries, 1):
            case_id = f"{prefix}{group}-{number:03d}"
            # `facts` holds everything the user ends up saying; a first turn does
            # not know what the follow-ups add.
            first = dict(entry["facts"])
            for _, _, field, _ in entry["turns"]:
                first.pop(field, None)
            try:
                truth = concluder.ground_truth(
                    first, [(slot, field, value) for slot, _, field, value in entry["turns"]]
                )
            except ValueError as error:
                raise ValueError(f"{case_id}: {error}") from error
            case: dict[str, Any] = {
                "id": case_id,
                "group": group,
                "source": "draft",
                "query": entry["query"],
            }
            if entry["turns"]:
                case["followups"] = [
                    {"expect_ask_slot": slot, "answer": answer}
                    for slot, answer, _, _ in entry["turns"]
                ]
            case.update(ground_truth=truth, verified=False, notes=entry["notes"])
            built.append(case)
    return built


def main() -> None:
    kb = get_knowledge_base()
    concluder = C.Concluder(kb)
    draft = build(DRAFT, concluder)
    # Hand-written manual cases appended by import_manual_cases.py are kept.
    manual = (
        [c for c in C.load_cases(C.DRAFT_PATH) if c["source"] == "manual"]
        if C.DRAFT_PATH.exists()
        else []
    )
    smoke = build(SMOKE, concluder, prefix="S-")
    for path, items in ((C.DRAFT_PATH, draft + manual), (C.SMOKE_PATH, smoke)):
        errors = C.validate_cases(items, kb)
        if errors:
            raise SystemExit("\n".join(errors))
        C.save_cases(path, items)
        counts = Counter(c["group"] for c in items)
        print(f"{path.relative_to(C.ROOT)}: {len(items)} case " + str(dict(sorted(counts.items()))))
    if manual:
        print(f"(giữ lại {len(manual)} case manual)")


if __name__ == "__main__":
    main()
