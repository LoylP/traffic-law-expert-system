# Changelog

## P1b
- `extract_report.md`: bảng vi phạm group theo (Điều, vehicle_class), thêm `override_reason` và danh sách violation bị đổi vehicle_class.
- Thêm `src/reasoning/gen_auto_rules.py` sinh `classify_auto.yaml` (priority 10); thêm vào `make data`.
- Engine: điều kiện `grounded_violation` (field `Facts.grounded_violations`); `vehicle_class` trong luật khớp cả lớp con, `VEH_ANY` khớp mọi phương tiện.
- KG: thêm node ontology/Act/Circumstance/Subject từ YAML và cạnh `INSTANCE_OF_ACT`, `REQUIRES_CONTEXT`, `ESCALATES_TO`, `SUBCLASS_OF`; cập nhật `src.kg.stats`, `kb_report`.

## P0
- Tái tạo dữ liệu vi phạm và knowledge graph từ văn bản đã xử lý; chuẩn hóa citation và phân loại phương tiện.
