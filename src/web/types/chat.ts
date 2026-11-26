// Mirrors the API contract (DESIGN §9, src/reasoning/schema.py).

export type FactValue = string | number | boolean | null | string[];

export type Facts = {
  vehicle_class: string | null;
  acts: string[];
  free_behaviors: string[];
  grounded_violations: string[];
  speed_limit_kmh: number | null;
  actual_speed_kmh: number | null;
  speed_over_kmh: number | null;
  drank_alcohol: boolean | null;
  bac_blood_mg_100ml: number | null;
  bac_breath_mg_l: number | null;
  alcohol_test_refused: boolean | null;
  speed_band: string | null;
  alcohol_level: string | null;
  road_type: string | null;
  time_context: string | null;
  violation_date: string | null;
  officer_signal: boolean | null;
  resistance: string[];
  consequence: string[];
  passengers_count: number | null;
  passenger_exception: boolean | null;
  passenger_helmet_exception: boolean | null;
  no_helmet_who: "driver" | "passenger" | "both" | null;
  subject: string;
  circumstances: string[];
  unknown_slots: string[];
  evidence: Record<string, string>;
};

export type Sanction = {
  type: string;
  duration_min: number | null;
  duration_max: number | null;
};

export type ConditionalPoints = {
  points: number;
  condition: string;
  source: string;
};

export type ConsultViolation = {
  citation_id: string;
  label: string;
  description: string;
  fine_range: [number, number] | null;
  recommended_fine: number;
  points_deducted: number;
  sanctions: Sanction[];
  legal_text: string | null;
  allowed_range_after_circumstances: [number, number] | null;
  points_conditional: ConditionalPoints[];
  org_rule_applied: boolean;
};

export type QuestionOption = {
  value: string | number | boolean;
  label: string;
};

export type Question = {
  field: string;
  text: string;
  options: QuestionOption[];
  input_type: string | null;
  unit: string | null;
  rule_id: string;
  slot: string;
  number_field: string | null;
  number_max: number | null;
};

export type BranchCondition = {
  slot: string;
  slot_label: string;
  values: (string | number)[];
  labels: string[];
};

export type ConsultBranch = {
  conditions: BranchCondition[];
  violations: ConsultViolation[];
};

export type TraceStep = {
  rule_id: string;
  type:
    | "derive"
    | "temporal"
    | "classify"
    | "escalate"
    | "exclude"
    | "note"
    | "ask"
    | "ground";
  matched_facts: Record<string, unknown>;
  produced: Record<string, unknown>;
  explain: string | null;
  source: string | null;
};

export type FactUsed = {
  field: string;
  value: unknown;
  evidence: string | null;
  origin?: "user" | "derived"; // missing on old history records
  derived_from?: string | null;
};

export type LegalCitation = {
  citation_id: string;
  label: string;
  text: string | null;
};

export type Explanation = {
  facts_used: FactUsed[];
  chain: TraceStep[];
  legal_citations: LegalCitation[];
  penalty_calc: string[];
  faithfulness_ok: boolean;
};

export type ConsultStatus = "answered" | "need_info" | "unknown" | "out_of_scope";

export type ConsultResponse = {
  session_id: string | null;
  status: ConsultStatus;
  facts: Facts;
  violations: ConsultViolation[];
  total_recommended_fine: number;
  questions: Question[];
  branches?: ConsultBranch[]; // missing on old history records
  depends_on?: string[];
  explanation: Explanation;
  answer_text: string;
  summary_text: string;
  notes: string[];
  total_points_deducted: number;
  sanctions: Sanction[];
  aggravating: string[];
  mitigating: string[];
  latency_ms: Record<string, number>;
};

// -- Legacy search (/search/hybrid, /search/llm) -------------------------------

export type LegacyMode = "hybrid" | "llm";
export type ChatMode = "expert" | LegacyMode;

export type SearchResult = {
  violation_id: string;
  raw_node: Record<string, unknown>;
  scores?: { bm25?: number; embedding?: number; hybrid?: number };
  vehicle_class?: string | null;
};

export type SearchResponse = {
  success: boolean;
  api_type: LegacyMode;
  original_query: string;
  processed_query: string | null;
  results: SearchResult[] | null;
  best_result: SearchResult | null;
};

// -- History -----------------------------------------------------------------

/** What /consult stores in `results[0]`. `result` is missing on old records. */
export type ConsultRecord = {
  session_id: string;
  status: ConsultStatus;
  violations: string[];
  total_recommended_fine: number;
  answer_text: string;
  result?: ConsultResponse;
};

export type HistoryItem = {
  id: number;
  api_type: string;
  original_query: string;
  processed_query: string | null;
  top_k: number;
  created_at: string;
  results: unknown[];
};

export type KnowledgeStats = {
  ontology: Record<string, number>;
  acts: VerifiedCount;
  circumstances: Record<string, VerifiedCount>;
  rules: Record<string, VerifiedCount>;
  rules_total: VerifiedCount;
};

export type VerifiedCount = { total: number; verified: number; unverified: number };

// -- Conversation ------------------------------------------------------------

export type ChatTurn = { id: string; at: string } & (
  | { kind: "user"; text: string }
  | { kind: "consult"; result: ConsultResponse }
  | { kind: "legacy"; response: SearchResponse }
  | { kind: "archived"; text: string }
  | { kind: "error"; message: string; retryText: string }
);
