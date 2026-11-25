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
