import type { Sanction } from "@/types/chat";

const money = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });

/** 19500000 -> "19.500.000 ₫" */
export function formatMoney(value: number): string {
  return `${money.format(value)}\u00a0₫`;
}

type CitationParts = { decree: string; article: string; clause?: string; point?: string };

/** "ND168-D7-K7-Pc" -> parts; null when the ID has another shape. */
export function parseCitation(citationId: string): CitationParts | null {
  const match = /^ND(\d+)-D(\d+)(?:-K(\d+))?(?:-P(.+))?$/.exec(citationId);
  if (!match) return null;
  const [, decree, article, clause, point] = match;
  return { decree, article, clause, point };
}

function citationUnits(parts: CitationParts): string[] {
  return [
    `Điều ${parts.article}`,
    parts.clause ? `Khoản ${parts.clause}` : "",
    parts.point ? `Điểm ${parts.point}` : "",
  ].filter(Boolean);
}

/** "Điều 7 · Khoản 7 · Điểm c" */
export function citationShort(citationId: string): string {
  const parts = parseCitation(citationId);
  return parts ? citationUnits(parts).join(" · ") : citationId;
}

const DECREES: Record<string, string> = {
  "100": "NĐ 100/2019/NĐ-CP",
  "123": "NĐ 123/2021/NĐ-CP",
  "168": "NĐ 168/2024/NĐ-CP",
};

/** "NĐ 168/2024/NĐ-CP, Điều 7 Khoản 7 Điểm c" (for the clipboard). */
export function citationFull(citationId: string): string {
  const parts = parseCitation(citationId);
  if (!parts) return citationId;
  const decree = DECREES[parts.decree] ?? `NĐ ${parts.decree}`;
  return `${decree}, ${citationUnits(parts).join(" ")}`;
}

export function sanctionLabel(sanction: Sanction): string {
  const names: Record<string, string> = {
    revoke_license: "Tước GPLX",
    confiscate: "Tịch thu phương tiện",
    remedy: "Buộc khắc phục hậu quả",
  };
  const name = names[sanction.type] ?? sanction.type;
  const { duration_min: min, duration_max: max } = sanction;
  if (min === null) return name;
  return max === null || max === min ? `${name} ${min} tháng` : `${name} ${min}–${max} tháng`;
}

/** SQLite CURRENT_TIMESTAMP is UTC without a zone marker. */
export function parseServerTime(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value.replace(" ", "T")}Z`);
}

export function formatDateTime(date: Date): string {
  return date.toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

export function dayGroup(date: Date, now = new Date()): string {
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(date)) / 86_400_000);
  if (days <= 0) return "Hôm nay";
  if (days === 1) return "Hôm qua";
  return date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function truncate(text: string, length = 60): string {
  const clean = text.trim().replace(/\s+/g, " ");
  return clean.length > length ? `${clean.slice(0, length - 1)}…` : clean;
}

/** Non-secure contexts (plain HTTP over LAN) have no crypto.randomUUID. */
export function newId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
