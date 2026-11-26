# Knowledge Base - Phase P1a

## Overview

Tri thức tường minh cho hệ chuyên gia tư vấn vi phạm luật giao thông, được tổ chức theo DESIGN §4-§5.

Tất cả file được sinh theo spec Phase P1a và có cờ `verified: false` (chờ kiểm tra bởi người).

## Structure

```
data/knowledge/
├── ontology.yaml              # Lớp, enum, quan hệ (§4.1-4.4)
├── acts.yaml                  # 12 hành vi (6 nhóm chính + phụ)
├── circumstances.yaml         # 20 tình tiết (7 giảm nhẹ + 13 tăng nặng)
├── rules/
│   ├── derive.yaml           # 26 luật suy diễn
│   ├── classify_core.yaml    # 27 luật phân loại (6 nhóm làm sâu)
│   ├── escalate.yaml         # 18 luật leo thang (gây tai nạn)
│   ├── note.yaml             # 1 luật ghi chú (chạy sau classify)
│   ├── ask.yaml              # 4 luật hỏi bổ sung
│   └── temporal.yaml         # 1 luật thời gian
└── verify_sheet.csv          # 84 rules cần verify
```

## Statistics

### Ontology
- **Vehicle Classes**: 7 (VEH_ANY → VEH_MOTOR → VEH_CAR/VEH_MOTORBIKE, etc.)
- **Alcohol Levels**: 3 (BAC_L1, BAC_L2, BAC_L3) với ngưỡng từ NĐ 168
- **Speed Bands**: 4 (5-10, 10-20, 20-35, >35 km/h) từ Điều 6, 7
- **Road Types**: 4 (cao tốc, khu dân cư, hầm, thường)
- **Time Contexts**: 2 (ngày, đêm 18h-6h)
- **Consequences**: 1 (gây tai nạn)
- **Resistance Behaviors**: 3 (bỏ chạy, cản trở, lăng mạ)
- **Subjects**: 2 (cá nhân, tổ chức)
- **Additional Sanctions**: 3 (tước quyền, tịch thu, khắc phục)

### Acts (12 total, 6 core)
Core acts (6 nhóm làm sâu):
1. **ACT_RED_LIGHT** - Không chấp hành đèn tín hiệu
2. **ACT_ALCOHOL** - Nồng độ cồn (3 mức)
3. **ACT_SPEEDING** - Chạy quá tốc độ (4 band)
4. **ACT_NO_HELMET** - Người lái không đội mũ (xe máy)
5. **ACT_PASSENGER_NO_HELMET** - Hành khách không đội mũ
6. **ACT_IGNORE_OFFICER** - Không chấp hành hiệu lệnh CSGT

Additional acts:
- ACT_WRONG_LANE, ACT_WRONG_WAY
- ACT_OVERLOAD_PASSENGER, ACT_PHONE_WHILE_DRIVING
- ACT_NO_LICENSE, ACT_OBSTRUCT_OFFICER

Mỗi act có ≥6 synonyms (cách nói đời thường) và related_violations (citation_id từ violations_168_clean.json).

**New acts added based on NĐ 168 review**:
- ACT_REFUSE_ALCOHOL_TEST - Không chấp hành yêu cầu kiểm tra nồng độ cồn
- ACT_HIT_AND_RUN - Gây tai nạn rồi bỏ chạy

### Circumstances (20 total)
**Giảm nhẹ (7)**: Luật XLVPHC Điều 9
- CIR_PREVENT_HARM (ngăn chặn hậu quả)
- CIR_VOLUNTARY_CONFESS (tự nguyện khai báo)
- CIR_PROVOKED (bị kích động)
- CIR_COERCED (bị ép buộc)
- CIR_PREGNANT_ELDERLY_DISABLED
- CIR_HARDSHIP (hoàn cảnh khó khăn)
- CIR_BACKWARD (trình độ lạc hậu)

**Tăng nặng (13)**: Luật XLVPHC Điều 10
- CIR_REPEAT (tái phạm)
- CIR_MULTIPLE_TIMES (vi phạm nhiều lần)
- CIR_INSULT_OFFICER (lăng mạ CSGT)
- CIR_CONTINUE_AFTER_STOP (tiếp tục dù đã can ngăn)
- CIR_CONCEAL (trốn tránh, che giấu)
- CIR_INCITE_MINOR (xúi giục trẻ em)
- ... (và 7 loại khác)

### Rules (74 total)

#### 1. Derive Rules (27)
Suy diễn gián tiếp, priority 50-60:
- **Speed**: 9 rules (tính speed_over_kmh, map → band → ACT_SPEEDING)
- **Alcohol**: 9 rules (map BAC → level → ACT_ALCOHOL)
- **Resistance**: 4 rules (RES_FLEE + officer_signal → ACT_IGNORE_OFFICER; RES_INSULT → CIR_INSULT_OFFICER; CONS_ACCIDENT + RES_FLEE + no officer_signal → ACT_HIT_AND_RUN)
- **Passengers**: 1 rule (xe máy ≥2 người → ACT_OVERLOAD_PASSENGER)
- **Helmet**: 3 rules (map no_helmet_who → acts)
- **Wrong way**: 1 rule (mô tả → ACT_WRONG_WAY)

#### 2. Classify Core Rules (33)
Phân loại viết tay cho 6 nhóm + new acts, priority 40:
- **Red light**: 2 rules (car, motorbike) → ND168-D6-K9-Pb / ND168-D7-K7-Pc
- **Alcohol**: 6 rules (3 mức × 2 loại xe)
- **Speeding**: 7 rules (4 band xe ô tô + 3 band xe máy)
- **Helmet**: 2 rules (người lái, hành khách)
- **Ignore officer**: 2 rules (car, motorbike)
- **Wrong lane/way**: 6 rules (4 base + 2 expressway classification)
- **Phone/Overload**: 4 rules
- **Refuse alcohol test**: 2 rules (car → ND168-D6-K11-Pb, moto → ND168-D7-K9-Pđ)
- **Hit and run**: 2 rules (car → ND168-D6-K8, moto → ND168-D7-K9-Pc)

Mỗi rule có `legal_excerpt` (≤200 ký tự nguyên văn) và `citation_id`.

#### 3. Escalate Rules (19)
Leo thang khi có CONS_ACCIDENT, priority 35:
- **Car**: 9 rules → ND168-D6-K10-Pa (tốc độ, wrong lane), K10-Pb (các vi phạm khác)
- **Motorbike**: 9 rules → ND168-D7-K10-Pa (tốc độ, wrong lane/way), K10-Pb (các vi phạm khác)
- (R-ESC-OUT-OBSTRUCT đã xoá; xem Note Rules)

#### 3b. Note Rules (1) — `note.yaml`, chạy sau classify/escalate/exclude, trước ask:
- **R-NOTE-OBSTRUCT**: ACT_OBSTRUCT_OFFICER → thêm `notes[]`; chỉ đặt `status=out_of_scope` khi không có violation nào

#### 4. Ask Rules (4)
Hỏi bổ sung khi thiếu dữ kiện, priority 20-25:
- Nồng độ cồn (4 options: 0.2 / 0.3 / 0.5 mg/l / `refuse` → `engine.apply_answer` đặt `alcohol_test_refused=true`, thêm ACT_REFUSE_ALCOHOL_TEST)
- Tốc độ thực tế, tốc độ cho phép (chỉ hỏi khi `speed_over_kmh` null)
- Loại phương tiện (5 options)

**Không hỏi** khi acts rỗng và không ground được → để unknown.

#### 5. Temporal Rules (1)
Chọn văn bản theo ngày, priority 70:
- Vi phạm < 2025-01-01 → out_of_scope_temporal (NĐ 100/2019)

## Verification Status

**Tất cả items có `verified: false`** (chờ kiểm tra bởi người).

File `verify_sheet.csv` chứa 84 rules cần verify với các cột:
- rule_id, type, when, then
- citation_id (nếu có)
- legal_excerpt (nếu có)
- verified (hiện tại false)

Người kiểm tra đối chiếu từng rule với nguyên văn trong:
- `data/processed/nghi_dinh_168.txt`
- `data/processed/luat_xlvphc_dieu_9_10.txt`
- `data/structured/violations_168_clean.json`

Sau khi verify, đổi `verified: false → true` trong file YAML tương ứng.

## Data Sources

| File | Mục đích |
|------|----------|
| `data/processed/nghi_dinh_168.txt` | Nguồn chính cho speed band, alcohol level, citation_id |
| `data/processed/luat_xlvphc_dieu_9_10.txt` | Nguồn **duy nhất** cho circumstances (Điều 9, 10) |
| `data/structured/violations_168_clean.json` | Nguồn citation_id cho acts.related_violations |

**Nguyên tắc**: KHÔNG viết từ trí nhớ, PARSE nguyên văn từ văn bản.

## Usage

```python
# Load knowledge base
from pathlib import Path
import yaml

KB_DIR = Path("data/knowledge")

ontology = yaml.safe_load((KB_DIR / "ontology.yaml").read_text())
acts = yaml.safe_load((KB_DIR / "acts.yaml").read_text())
circumstances = yaml.safe_load((KB_DIR / "circumstances.yaml").read_text())

# Load rules
derive_rules = yaml.safe_load((KB_DIR / "rules/derive.yaml").read_text())
classify_rules = yaml.safe_load((KB_DIR / "rules/classify_core.yaml").read_text())
# ...
```

## Testing

```bash
# Run validation tests
pytest tests/test_knowledge_files.py -v

# Generate report
python -m src.reasoning.kb_report
```

## Next Steps (Phase P1b, P1c)

1. **P1b**: Implement InferenceEngine sử dụng các rules này
   - Forward chaining theo thứ tự: derive → temporal → classify → escalate → exclude → ask
   - Conflict resolution: priority > specificity > order
   - Ghi TraceStep mỗi lần fire

2. **P1c (optional)**: Luật classify_auto.yaml
   - Sinh tự động từ violations_168_clean.json
   - Priority thấp hơn classify_core
   - Áp dụng cho các vi phạm không nằm trong 6 nhóm làm sâu

3. **Verification**: Người kiểm tra đối chiếu và đổi `verified: true`

## Notes

- Tất cả ID enum phải khớp với DESIGN §4
- Mọi citation_id phải resolve được trong law_corpus (check sau khi có corpus)
- Mọi ngưỡng số (BAC, speed) phải verify với nguyên văn
- Synonyms phải có ≥6 cách nói đời thường cho mỗi act/circumstance

---

Generated by Phase P1a - Knowledge Base Creation  
Updated: 2025-11-26 (with NĐ 168 review corrections)  
Status: **All files created, updated with NĐ 168 review results, waiting for verification**
