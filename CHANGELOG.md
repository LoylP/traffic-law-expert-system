# Changelog

## P2.2
- Đối chiếu 56 violation mất `sanctions` so với bản commit trước: tất cả là `remedy` gán nhầm từ chữ “buộc” trong mô tả hành vi, giữ bỏ; không đổi logic gán chế tài. Thêm test cho tước GPLX cồn mức 3 (ô tô, xe máy) và các trường hợp gán nhầm.
- Điểm trừ có điều kiện (Điều 20 K2, K4; Điều 32 K5, K6): `points_deducted` giữ mức thấp (4), thêm `points_conditional`; `PenaltyDecider` và CLI hiển thị điều kiện, không tự áp.
- Lỗi dính chữ: không tái hiện được trong dữ liệu và output; thêm test chặn hồi quy trên output của các example.

## P2.1
- `violation_extract.py`: dẫn chiếu nguyên khoản (điểm trừ GPLX, hình thức bổ sung, biện pháp khắc phục) áp dụng cho mọi vi phạm của khoản; số vi phạm có trừ điểm 143 → 204.
- Bỏ chế tài gán nhầm: chỉ đọc chế tài từ khoản không phải khoản phạt tiền (tránh khớp “bắt buộc”, “chằng buộc”) và bỏ qua phần “trừ hành vi/trường hợp…”; số vi phạm có chế tài 159 → 127.
- `extract_report.md`: thêm bảng trước/sau và danh sách mức trừ điểm phụ thuộc điều kiện.
- `explain.py`: tiêu đề trích dẫn ghi “Điều X khoản Y” (`LegalCitation.text` giữ nguyên văn).
- `violation_overlaps` của `CIR_INSULT_OFFICER`: `verified: true`.

## P2
- Lõi suy luận offline: mở rộng `schema.py` (`EngineResult`, penalty, `Explanation`, `ConsultResult`), `knowledge_base.py` (acts, tình tiết, vi phạm, LegalUnit, cache singleton, cờ `include_unverified`).
- Engine: `run()` (giữ `infer()`), `enabled_rule_types`, toán tử `has_circumstance`, fire một lần cho mỗi binding, loại hit tổng quát khi cùng act có hit cụ thể hơn (kể cả hit đã leo thang).
- Mới: `penalty.py`, `explain.py`, `cli.py`, 5 file `examples/facts_*.json`, `tests/test_penalty.py`.
- `circumstances.yaml`: thêm `violation_overlaps` (khoản 2 Điều 10 Luật XLVPHC), `verified: false`.

## P1b
- `extract_report.md`: bảng vi phạm group theo (Điều, vehicle_class), thêm `override_reason` và danh sách violation bị đổi vehicle_class.
- Thêm `src/reasoning/gen_auto_rules.py` sinh `classify_auto.yaml` (priority 10); thêm vào `make data`.
- Engine: điều kiện `grounded_violation` (field `Facts.grounded_violations`); `vehicle_class` trong luật khớp cả lớp con, `VEH_ANY` khớp mọi phương tiện.
- KG: thêm node ontology/Act/Circumstance/Subject từ YAML và cạnh `INSTANCE_OF_ACT`, `REQUIRES_CONTEXT`, `ESCALATES_TO`, `SUBCLASS_OF`; cập nhật `src.kg.stats`, `kb_report`.

## P0
- Tái tạo dữ liệu vi phạm và knowledge graph từ văn bản đã xử lý; chuẩn hóa citation và phân loại phương tiện.
