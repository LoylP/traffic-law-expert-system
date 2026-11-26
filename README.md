# Hệ thống hỏi đáp Luật Giao thông theo ngữ nghĩa

## Tổng quan

Hệ thống hỏi đáp luật giao thông dựa trên ngữ nghĩa, hỗ trợ truy vấn các vi phạm giao thông theo Nghị định 168/2024/NĐ-CP.

Nguồn: Thư viện pháp luật
Link: https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/01/168-nd-cp.signed.pdf
---


## Quy trình xây dựng bộ dữ liệu 300 vi phạm giao thông

### 1. Đọc & chuẩn hóa văn bản đầu vào

- Hỗ trợ file `.txt` hoặc `.docx`
- Chuẩn hóa khoảng trắng: thay thế `\u00a0` (non-breaking space), gộp nhiều khoảng trắng thành một:

```python
text = re.sub(r"\s+", " ", text)
```

---

### 2. Phân cấp cấu trúc văn bản (3 lớp regex)

| Lớp | Regex | Ví dụ |
|-----|-------|-------|
| Điều | `Điều\s+(\d+)\.\s*(.*?)(?=\sĐiều\s+\d+\.|$)` | Điều 6, Điều 7... |
| Khoản | `(\d+)\.\s*(.*?)(?=\s\d+\.\s\|$)` | 1., 2., 3... |
| Điểm | `([a-zđ])\)\s*(.*?)(?=\s[a-zđ]\)\s\|$)` | a), b), c)... |

> Chỉ xử lý **Điều 6–40** (phần quy định xử phạt), bỏ qua phần đầu/cuối văn bản.

---

### 3. Trích xuất thông tin từng vi phạm

Với mỗi điểm/khoản hợp lệ, script dùng regex để trích xuất:

#### a) Mức phạt tiền

Pattern: `phạt tiền từ X đồng đến Y đồng`

Lấy `fine_min`, `fine_max` bằng cách strip ký tự không phải số.

#### b) Biện pháp bổ sung (tước, tịch thu, đình chỉ...)

- Nhận dạng câu dẫn: `ngoài việc bị...` / `ngoài ra...`
- Tìm 7 loại sanction unit cụ thể:
  - `tước quyền sử dụng`
  - `tịch thu`
  - `đình chỉ`
  - `buộc`
  - `cấm`
  - `trục xuất`
  - `thu hồi`
- Ánh xạ sanction vào đúng (khoản, điểm) để gán cho vi phạm đúng.

#### c) Loại phương tiện

Keyword matching trong tiêu đề điều luật: `ô tô`, `mô tô`, `xe máy`, `xe đạp`, `người đi bộ`...

#### d) Điều kiện hoàn cảnh

Keyword matching: `đường cao tốc`, `đèn tín hiệu`, `nồng độ cồn`, `hầm đường bộ`...

#### e) Cơ sở pháp lý

Xây dựng dạng:

```
corpus://dataset-traffic-law#dieu-X-khoan-Y-diem-Z | NĐ 168/2024, Điều X Khoản Y Điểm Z
```

---

### 4. Tái tạo dữ liệu P0

Chạy `make data` để lần lượt dựng law corpus, trích xuất vi phạm NĐ 168,
xây knowledge graph và in thống kê. Chạy `make test` để kiểm tra tính toàn
vẹn của citation, mức phạt, phương tiện và cạnh `BASED_ON`.

Mỗi bản ghi trong `data/structured/violations_168_clean.json` có
`citation_id`, `description`, `description_full`, `vehicle_class`,
`fine_min`/`fine_max`, mức phạt tổ chức (nếu có), `points_deducted`,
`sanctions`, `consequence_accident`, `excludes` và nguyên văn `legal_text`.
Các citation dùng chung định dạng chuẩn của `law_corpus.jsonl`.

---

## Evaluation

Thiết kế: nhóm case, chỉ số và ablation (DESIGN §11). Logic đánh giá nằm trong `src/eval/`; notebook chỉ gọi lại.

### Định dạng case (`data/eval/*.jsonl`, mỗi dòng một case)

```json
{"id": "E-002", "group": "E", "source": "draft", "query": "vượt đèn đỏ bị sao",
 "followups": [{"expect_ask_slot": "vehicle", "answer": "Ô tô"}],
 "ground_truth": {"facts": {"vehicle_class": "VEH_CAR", "acts": ["ACT_RED_LIGHT"]},
   "first_status": "need_info", "first_ask_slot": "vehicle", "status": "answered",
   "violations": ["ND168-D6-K9-Pb"], "recommended_fine_total": 19000000, "points_deducted_total": 4,
   "sanctions": [], "aggravating": [], "mitigating": []},
 "verified": false, "notes": ""}
```

- Nhóm (số case tối thiểu): A tra cứu đơn (15), B đời thường/gián tiếp (20), C nhiều hành vi (15), D tình tiết/hậu quả/tổ chức (20), E thiếu dữ kiện/ngoài phạm vi (10).
- `facts`: chỉ slot người dùng thực sự nói, kể cả câu trả lời ở `followups`. `acts` gồm các hành vi lời kể nêu ra; không ghi giá trị do luật suy ra (vd `speed_over_kmh` khi chỉ nói tốc độ chạy và giới hạn).
- `status`: `answered` | `need_info` | `unknown` (`out_of_scope` được quy về `unknown`).
- `first_ask_slot`, `expect_ask_slot`: `vehicle` | `alcohol` | `speed` | `passengers` | `road`.
- `sanctions`: loại hình phạt bổ sung (`revoke_license`, `confiscate`, `remedy`).

### Tạo và kiểm tra bộ test

```bash
python scripts/draft_test_cases.py          # -> test_cases.draft.jsonl, smoke_cases.jsonl
cp data/eval/manual_cases.example.csv data/eval/manual_cases.csv   # rồi viết câu hỏi của bạn
python scripts/import_manual_cases.py       # nối case manual vào draft
python scripts/export_verify_sheet.py       # -> verify_cases.csv (giữ nguyên dòng đã sửa)
# kiểm tra tay: sửa ground truth, đặt verified=true
python scripts/apply_verification.py        # -> test_cases.jsonl (chỉ dòng verified=true)
make eval-validate
```

Kết luận trong draft (violations, tiền, điểm...) do chính engine tính từ `facts`; facts của case manual do RegexExtractor gợi ý. Vì vậy trước khi verify, `oracle_facts` luôn đúng 100% và `regex_extractor` được lợi trên case manual. Khi verify phải đối chiếu với **nguyên văn nghị định**, không chỉ xác nhận lại cột có sẵn. Trong sheet: danh sách ngăn bằng `|`, facts dạng `slot=giá trị; slot=a|b`. Muốn sửa câu hỏi hoặc followup thì sửa trong draft.

### Chạy local

```bash
make eval-smoke    # oracle_facts + regex_extractor trên smoke_cases -> data/eval/smoke_results/
make eval-local    # hai config không LLM trên test_cases.jsonl -> data/eval/results/_no_llm/
python -m src.eval.run_eval --config all --model qwen3.5:4b-q4_K_M --resume   # cần Ollama
python -m src.eval.aggregate                                                  # -> data/eval/report/
```

| Config | Khác `full` |
|---|---|
| `full` | pipeline như `/consult`; gặp `need_info` thì gửi lần lượt `followups` (tối đa 3) |
| `no_derive` / `no_circumstance` / `no_grounder` | tắt luật derive / tình tiết (luôn mức trung bình) / OntologyGrounder |
| `regex_extractor` | RegexExtractor thay LLM |
| `oracle_facts` | đưa `ground_truth.facts` thẳng vào engine (trần của suy luận; không đo trích xuất, hội thoại) |
| `llm_only` | baseline không engine: retriever top-10 -> LLM tự kết luận (prompt ở `src/eval/llm_only.py`) |

Tham số khác: `--cases`, `--limit N`, `--out`, `--resume`, `--seed 42`, `--writer-sample 20`, `--check-complete`.

### Định nghĩa cần lưu ý

- Slot P/R/F1 tính trên cặp (slot, giá trị); giá trị rỗng, `false` và `subject` mặc định coi là không điền; không chấm `free_behaviors`. Facts dự đoán = facts hội thoại đã trích cộng hành vi do grounder ánh xạ.
- Hallucinated-slot rate: số slot được điền mà ground truth không có / số slot được điền.
- `citation_acc`: tỉ lệ vi phạm trong ground truth được trích đúng Điều–Khoản (bỏ qua Điểm). `citation_exists`: tỉ lệ citation hệ đưa ra có trong KB/corpus.
- Fine-range, fine exact, points, aggravating, mitigating chỉ tính trên case có `status = answered`; violation và sanctions tính trên mọi case.
- End-to-end: status cuối đúng, và nếu `answered` thì đúng cả tập vi phạm, tổng tiền và điểm (sanctions báo riêng).
- Độ trễ chỉ lấy từ lần gọi thật. Ablation dùng lại cache trích xuất của `full` nên không có `extract`/`total`. `write` là answer writer LLM, đo trên mẫu writer, không nằm trong `total`.
- `errors.csv`: loại lỗi chính theo thứ tự `ground` > `extract` > `rule` > `penalty` > `dialog` (gán tự động, dùng để lọc khi phân tích).

### Chạy trên Colab

1. Commit `data/eval/test_cases.jsonl` cùng mã nguồn, tạo tag `eval-v1` và push.
2. Mở `notebooks/colab_eval.ipynb`, chọn runtime GPU, chỉnh ô biến (`REF`, `LIMIT`, `MODELS`, `DRIVE_OUT`) rồi chạy lần lượt. Mất kết nối thì chạy lại: kết quả và cache nằm trên Drive, `--resume` bỏ qua case đã xong.
3. Chỉ so sánh độ trễ giữa các model chạy trên cùng loại GPU (`aggregate` sẽ cảnh báo).

Cache khoá theo tên model, không theo digest: nếu tag model được cập nhật, hãy xoá `data/eval/cache/<model>/`. Đổi prompt hoặc schema thì khoá cache tự đổi; đổi mã nguồn khác thì chạy lại không dùng `--resume`.

### Cấu trúc kết quả

```
data/eval/results/<model>/<config>/        # config không LLM: results/_no_llm/<config>/
  per_case.jsonl   ghi sau mỗi case (dự đoán, từng lượt, độ trễ, lời gọi LLM, mẫu writer)
  per_case.csv     đối chiếu ground truth / dự đoán
  errors.csv       case sai + loại lỗi
  summary.json     chỉ số tổng và theo nhóm A–E, độ trễ, faithfulness, env
data/eval/report/  ablation.{xlsx,md}, models.{xlsx,md}, *.png
```
