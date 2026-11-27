# Báo cáo suy luận OWL

Sinh tự động bởi `python -m src.kg.export_owl` (`make owl`). Không sửa tay.

## Ontology đã xuất (`traffic.owl`, chỉ gồm tiên đề khẳng định)

| Thành phần | Số lượng |
|---|---:|
| Violation | 634 |
| Act | 19 |
| Circumstance | 20 |
| LegalProvision | 2756 |
| Lớp | 31 |
| Object property | 8 |
| Data property | 4 |
| Tổng số cá thể | 3459 |

## Kết quả suy luận

- Java: openjdk version "27.0.1.1" 2026-11-17
- Reasoner: Pellet (owlready2 0.51)
- Tính nhất quán: **NHẤT QUÁN**
- Thời gian suy luận (gồm khởi động JVM): 3.67 giây
- Lớp không thỏa được: không có

## Defined classes

| Lớp | Định nghĩa |
|---|---|
| AlcoholViolation | Violation ⊓ ∃instanceOfAct.{ACT_ALCOHOL} |
| CarViolation | Violation ⊓ ∃appliesToVehicle.VEH_CAR |
| MotorVehicleViolation | Violation ⊓ ∃appliesToVehicle.VEH_MOTOR |
| LicenseRevokingViolation | Violation ⊓ ∃hasSanction.RevokeLicenseSanction |
| EscalatedViolation | Violation ⊓ ∃escalatedFrom.Violation (escalatedFrom ≡ escalatesTo⁻) |
| HighPointViolation | Violation ⊓ ∃pointsDeducted.xsd:integer[≥ 10] |

## Đối chiếu số cá thể được phân lớp

| Defined class | Reasoner | Đếm từ KG | Đếm từ KB | So tập citation_id |
|---|---:|---:|---:|---|
| AlcoholViolation | 6 | 6 | 6 | khớp |
| CarViolation | 238 | 238 | 238 | khớp |
| MotorVehicleViolation | 349 | 349 | 349 | khớp |
| LicenseRevokingViolation | 17 | 17 | 17 | khớp |
| EscalatedViolation | 4 | 4 | 4 | khớp |
| HighPointViolation | 14 | 14 | 14 | khớp |

- **Đếm từ KG**: đọc trực tiếp `kg_nodes.jsonl`, `kg_edges.jsonl`.
- **Đếm từ KB**: đọc `violations_168_clean.json`, `ontology.yaml`, `acts.yaml`, `rules/escalate.yaml` (không qua KG).
- OWL được dựng từ KG nên cột KB là phép kiểm tra độc lập hơn.

## Thành viên các lớp nhỏ (≤ 20, theo KB)

- **AlcoholViolation**: ND168-D6-K11-Pa, ND168-D6-K6-Pc, ND168-D6-K9-Pa, ND168-D7-K6-Pa, ND168-D7-K8-Pb, ND168-D7-K9-Pd
- **LicenseRevokingViolation**: ND168-D12-K14-Pa, ND168-D12-K14-Pb, ND168-D6-K11-Pa, ND168-D6-K11-Pb, ND168-D6-K11-Pc, ND168-D6-K11-Pd, ND168-D6-K12, ND168-D6-K13, ND168-D7-K9-Pa, ND168-D7-K9-Pb, ND168-D7-K9-Pd, ND168-D7-K9-Pe, ND168-D7-K9-Pg, ND168-D7-K9-Ph, ND168-D7-K9-Pi, ND168-D7-K9-Pk, ND168-D7-K9-Pđ
- **EscalatedViolation**: ND168-D6-K10-Pa, ND168-D6-K10-Pb, ND168-D7-K10-Pa, ND168-D7-K10-Pb
- **HighPointViolation**: ND168-D13-K8-Pa, ND168-D21-K11, ND168-D21-K8-Pa, ND168-D21-K8-Pb, ND168-D32-K13-Pd, ND168-D32-K16-Pb, ND168-D34-K5-Pb, ND168-D6-K10-Pa, ND168-D6-K10-Pb, ND168-D6-K11-Pđ, ND168-D6-K9-Pa, ND168-D7-K10-Pa, ND168-D7-K10-Pb, ND168-D7-K8-Pb

## Giới hạn khi đọc kết quả

- Khớp số liệu chứng tỏ phép phân lớp OWL tái lập đúng KG/KB; nó **không** chứng minh KG/KB đúng với văn bản luật.
- `AlcoholViolation` chỉ gồm vi phạm được `acts.yaml` gắn với `ACT_ALCOHOL`. Còn 10 vi phạm có chữ “nồng độ cồn” trong mô tả nhưng không có cạnh này (có thể gồm cả hành vi chỉ nhắc đến, không phải hành vi uống rượu, bia khi điều khiển xe): ND168-D6-K11-Pb, ND168-D7-K9-Pđ, ND168-D8-K6-Pc, ND168-D8-K7-Pa, ND168-D8-K9-Pa, ND168-D8-K9-Pb, ND168-D9-K1-Pp, ND168-D9-K3-Pd, ND168-D9-K4-Pb, ND168-D9-K4-Pc.
- `CarViolation` chỉ gồm vi phạm gắn với `VEH_CAR` hoặc lớp con. Vi phạm gắn `VEH_ANY` / `VEH_MOTOR` có thể áp dụng cho ô tô nhưng không được suy ra là riêng của ô tô.
- Mỗi lớp `VEH_*` có một cá thể đại diện `VEH_*_individual` làm đích của `appliesToVehicle`; phân cấp xe nằm ở quan hệ lớp con.
- `HighPointViolation` chỉ tính `pointsDeducted`, không tính mức trừ điểm có điều kiện.
- `requiresContext` không giữ được ngữ nghĩa “một trong các ngữ cảnh” (`any_of`) và `escalatesTo` không giữ hậu quả kích hoạt; luật suy luận đầy đủ nằm ở `rules/*.yaml`.
- Giả định thế giới mở: chỉ định nghĩa lớp bằng điều kiện tồn tại (∃), không dùng phủ định.
