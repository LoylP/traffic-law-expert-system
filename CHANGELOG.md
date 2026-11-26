# Changelog

## P3b.2
- Nguyên tắc “không tự điền dữ kiện”: RegexExtractor và LLM extractor không còn tự suy `ACT_SPEEDING` từ số km/h, `ACT_ALCOHOL` / `drank_alcohol` từ nhau, tai nạn hay phản ứng từ hành vi; mọi suy diễn nằm ở derive rule (có trace). Phương tiện chỉ lấy khi câu nêu rõ (`vehicle_mapping.match_user_vehicles`). LLM: schema cho null ở mọi slot, thêm 3 ví dụ đối lập, chốt chặn xác định bỏ giá trị câu không nêu.
- Từ đồng nghĩa: bỏ “phóng nhanh”, “chạy tốc độ cao”, “đã từng bị (xử) phạt”; thêm “quá tốc độ” và các cách nói tái phạm nêu rõ “lỗi này”. Từ đồng nghĩa bắt đầu bằng đi/chạy/lái cho phép chen tên xe sau động từ.
- Derive mới: suy ô tô từ dây an toàn, mô tô/xe gắn máy từ mũ bảo hiểm (kèm ghi chú ngoại lệ); khoảng tốc độ / mức cồn; uống rượu, bia; từ chối kiểm tra cồn. Thêm `ACT_NO_SEATBELT`, `ACT_PASSENGER_NO_SEATBELT` và 2 classify rule. Luật mới và `ask.yaml` để `verified: false`.
- Hỏi lại tổng quát: `ask.yaml` chỉ khai báo slot; engine thử giá trị các slot thiếu, chỉ hỏi slot làm đổi Điều/Khoản/Điểm, mỗi lượt 1 câu, luôn có “Không rõ”, tối đa 3 lượt; sau đó trả các nhánh khả năng.
- `Facts` thêm `speed_band`, `alcohol_level` (chọn khoảng không ghi số đo giả), `unknown_slots`; `Question` thêm `slot`, `number_field`, `number_max`; `ConsultResult` thêm `branches`, `depends_on`; `FactUsed` thêm `origin`, `derived_from`.
- Web: hiển thị nhánh khả năng, “suy ra từ …”, ô nhập số đo cạnh các lựa chọn.
- Test: mới `tests/test_no_assumption.py`.

## P3b.1
- Session chỉ gộp facts khi lượt trước là `need_info`; sau `answered` / `unknown` / `out_of_scope`, lượt mới bắt đầu từ facts trống (giữ `session_id`). Thêm từ đồng nghĩa “đã từng bị phạt” cho `CIR_REPEAT`.
- AnswerWriter: LLM chỉ nhận nhãn căn cứ, tổng tiền, điểm GPLX, hình thức bổ sung và số tình tiết (không còn mô tả, khung phạt, mức phạt từng hành vi); dùng template nếu câu trả lời có “miligam”, “km/h” hoặc số không có trong payload.
- Web: chip gợi ý nhanh chỉ hiện khi chưa có tin nhắn; thêm padding dưới vùng tin nhắn; `devIndicators: false`; khi mở “Vì sao?”, header và phần tô bằng chứng theo đúng câu hỏi của câu trả lời đang chọn; bỏ việc tự mở vụ việc mới sau `out_of_scope`.

## P3b
- `src/web` thiết kế lại toàn bộ: token màu light/dark (`@theme`), Be Vietnam Pro, bố cục 3 vùng + drawer/bottom sheet, màn chào 6 gợi ý, thẻ kết quả, panel “Vì sao?”, hỏi bổ sung, trạng thái lỗi/đang xử lý, vụ việc gần đây, trang lịch sử mở lại kết quả chỉ xem; giữ tra cứu cũ trong “Nâng cao”. Xoá `components/chatbot/`; thêm `clsx`.
- `.gitignore`: bỏ ignore `src/web/lib/` (luật `lib/` của Python làm mất các file helper của web).
- API: thêm `GET /knowledge/labels`; history `consult` lưu thêm toàn bộ response (`result`).
- `ConsultResult` thêm trường (chỉ bổ sung): `summary_text`, `notes`, `total_points_deducted`, `sanctions`, `aggravating`, `mitigating`; `ConsultViolation` thêm `allowed_range_after_circumstances`, `points_conditional`, `org_rule_applied`. Lý do: web không phải tự tính lại từ dữ liệu pháp lý.
- Sửa lỗi extractor: “gây tai nạn” không còn bị gán `ACT_HIT_AND_RUN` nếu câu không nói người lái bỏ đi/không dừng lại.

## P3
- Mới: `llm_client.py` (ollama native / openai_compatible / gemini; constrained → prompt_only, bỏ `<think>`, retry, cache, metadata chế độ), `extractor_llm.py`, `extractor_regex.py`, `grounder.py`, `answer_writer.py`, `pipeline.py`.
- Chốt chặn xác định trên output LLM: bỏ ID lạ, số tốc độ/nồng độ cồn/ngày không có trong câu, `ACT_HIT_AND_RUN` khi câu không nói tai nạn, `ACT_SPEEDING` khi câu không nói tốc độ; câu trả lời sai số tiền/Điều/khoản/điểm/tháng/hình thức phạt thì dùng template.
- Grounder: thêm ngưỡng `GROUND_MIN_COSINE` (0.84) vì điểm hybrid là min-max trong tập ứng viên (câu không liên quan vẫn đạt ~1.0); vi phạm thuộc luật core được ánh xạ về Act. Ngưỡng mới thử trên ít câu, cần chỉnh ở P4.
- API: `POST /consult`, `GET /knowledge/stats`; không còn bắt buộc `GOOGLE_API_KEY`; `/search/llm` dùng `LLMClient`.
- `LegalRetriever.search`: thêm `vehicle_classes`, `threshold` (tùy chọn); tính lại cache embedding khi số dòng lệch.
- `TraceStep.type` thêm `ground`; thêm `ExtractionResult`; `kb_report.kb_stats()`; `.env.example`, `scripts/demo_consult.sh`; `.gitignore` bỏ qua cache embedding và DB lịch sử.
- Test: `tests/test_pipeline_offline.py`, `tests/test_llm_layer.py`.

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
