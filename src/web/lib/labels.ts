"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

import { fetchLabels } from "@/lib/api";
import { citationShort, formatMoney, parseCitation } from "@/lib/format";

// ID -> Vietnamese label, loaded once from GET /knowledge/labels.
let labels: Record<string, string> = {};
let pending: Promise<void> | null = null;
const listeners = new Set<() => void>();
const EMPTY: Record<string, string> = {};

function load() {
  pending ??= fetchLabels()
    .then((data) => {
      labels = data.labels;
      listeners.forEach((notify) => notify());
    })
    .catch(() => {
      pending = null; // retry on the next mount; IDs are shown meanwhile
    });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Names of Facts fields and trace keys (UI wording, not ontology IDs). */
const FIELD_LABELS: Record<string, string> = {
  vehicle_class: "Loại phương tiện",
  acts: "Hành vi",
  free_behaviors: "Hành vi mô tả tự do",
  free_behavior: "Cụm mô tả",
  grounded_violations: "Vi phạm ánh xạ trực tiếp",
  speed_limit_kmh: "Tốc độ cho phép",
  actual_speed_kmh: "Tốc độ thực tế",
  speed_over_kmh: "Vượt quá tốc độ",
  drank_alcohol: "Đã uống rượu, bia",
  bac_blood_mg_100ml: "Nồng độ cồn trong máu",
  bac_breath_mg_l: "Nồng độ cồn trong khí thở",
  alcohol_test_refused: "Từ chối kiểm tra nồng độ cồn",
  speed_band: "Khoảng vượt tốc độ",
  alcohol_level: "Mức nồng độ cồn",
  missing_slot: "Dữ kiện còn thiếu",
  depends_on: "Kết quả phụ thuộc",
  pending_violations: "Chờ dữ kiện để kết luận",
  set_facts: "Suy ra",
  road_type: "Loại đường",
  time_context: "Thời điểm",
  violation_date: "Ngày vi phạm",
  officer_signal: "Có hiệu lệnh của người thi hành công vụ",
  resistance: "Phản ứng với người thi hành công vụ",
  consequence: "Hậu quả",
  passengers_count: "Số người được chở",
  passenger_exception: "Thuộc ngoại lệ chở người",
  passenger_helmet_exception: "Thuộc ngoại lệ mũ bảo hiểm",
  no_helmet_who: "Người không đội mũ",
  subject: "Chủ thể vi phạm",
  circumstances: "Tình tiết",
  contexts: "Ngữ cảnh",
  has_act: "Có hành vi",
  has_context: "Có ngữ cảnh",
  has_circumstance: "Có tình tiết",
  has_violation: "Đã có vi phạm",
  also_has_violation: "Đồng thời có vi phạm",
  grounded_violation: "Vi phạm ánh xạ ngữ nghĩa",
  violation: "Xác định vi phạm",
  violations: "Vi phạm",
  escalated: "Chuyển khung",
  excluded: "Loại bỏ",
  removed: "Loại bỏ",
  question: "Cần hỏi",
  note: "Ghi chú",
  status: "Trạng thái",
  message: "Thông báo",
  candidates: "Ứng viên",
  from: "Từ",
  to: "Sang",
};

const VALUE_LABELS: Record<string, string> = {
  driver: "Người điều khiển",
  passenger: "Người ngồi sau",
  both: "Cả người điều khiển và người ngồi sau",
  out_of_scope_temporal: "Ngoài phạm vi thời gian",
};

const UNITS: Record<string, string> = {
  speed_limit_kmh: "km/h",
  actual_speed_kmh: "km/h",
  speed_over_kmh: "km/h",
  bac_blood_mg_100ml: "mg/100 ml máu",
  bac_breath_mg_l: "mg/l khí thở",
};

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

export function useLabels() {
  const map = useSyncExternalStore(subscribe, () => labels, () => EMPTY);
  useEffect(load, [map]);

  const idLabel = useCallback(
    (id: string) =>
      map[id] ?? VALUE_LABELS[id] ?? (parseCitation(id) ? citationShort(id) : id),
    [map],
  );

  /** Readable form of any fact or trace value. */
  const valueLabel = useCallback(
    (value: unknown, field = ""): string => {
      const render = (item: unknown, key: string): string => {
        if (item === null || item === undefined || item === "") return "chưa rõ";
        if (typeof item === "boolean") return item ? "Có" : "Không";
        if (typeof item === "number") {
          if (key.startsWith("fine")) return formatMoney(item);
          const text = item.toLocaleString("vi-VN", { maximumFractionDigits: 3 });
          return UNITS[key] ? `${text} ${UNITS[key]}` : text;
        }
        if (typeof item === "string") {
          if (key === "question" || key === "field" || key === "missing_slot") {
            return fieldLabel(item);
          }
          const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(item);
          return date ? `${date[3]}/${date[2]}/${date[1]}` : idLabel(item);
        }
        if (Array.isArray(item)) {
          return item.length ? item.map((v) => render(v, key)).join("; ") : "không có";
        }
        return Object.entries(item as Record<string, unknown>)
          .map(([k, v]) => `${fieldLabel(k)}: ${render(v, k)}`)
          .join(", ");
      };
      return render(value, field);
    },
    [idLabel],
  );

  /** Replace raw IDs that appear inside a server-written sentence. */
  const humanize = useCallback(
    (text: string) =>
      text.replace(
        /ND\d+-D\d+(?:-K\d+)?(?:-P[a-zđ]+)?|\b(?:ACT|CIR|VEH|BAC|SPEED|RES|CONS|ROAD|TIME|SUBJ)_[A-Z0-9_]+/g,
        (id) => idLabel(id),
      ),
    [idLabel],
  );

  return { idLabel, valueLabel, humanize };
}
