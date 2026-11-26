#!/usr/bin/env bash
# Six sample /consult calls. Start the API first:
#   uvicorn src.api.app:app --port 8000
# USE_LLM=false uses the RegexExtractor (the LLM answer writer stays on).
set -euo pipefail

API="${API:-http://localhost:8000}"
USE_LLM="${USE_LLM:-true}"
SESSION="demo-$$-$(date +%s)"

ask() {
  local title="$1" message="$2" session="${3:-}"
  local session_json=null
  [ -n "$session" ] && session_json="\"$session\""
  printf '\n=== %s\n>>> %s\n' "$title" "$message" >&2
  curl -sS --fail-with-body -X POST "$API/consult" \
    -H 'Content-Type: application/json' \
    -d "{\"message\": \"$message\", \"session_id\": $session_json, \"use_llm_extractor\": $USE_LLM}" |
    python3 -c '
import json, sys
r = json.load(sys.stdin)
if "--full" not in sys.argv:
    r.pop("explanation", None)
    for v in r.get("violations", []):
        v.pop("legal_text", None)
    r["facts"] = {k: v for k, v in r.get("facts", {}).items() if v not in (None, [], {})}
print(json.dumps(r, ensure_ascii=False, indent=2))
' ${FULL:+--full}
}

ask "1. Vi phạm đơn" "Tôi đi xe máy vượt đèn đỏ thì bị phạt thế nào?"
ask "2. Nhiều hành vi" "Xe máy chạy 75 km/h ở đoạn giới hạn 50 km/h, người lái không đội mũ bảo hiểm"
ask "3. Gián tiếp + tình tiết" "Đi xe máy, CSGT ra hiệu dừng xe nhưng tôi bỏ chạy và chửi bới CSGT"
ask "4. Thiếu dữ kiện (need_info)" "Tôi uống rượu rồi lái ô tô" "$SESSION"
ask "5. Trả lời bổ sung cùng session" "0,3 mg/l" "$SESSION"
ask "6. Ngoài phạm vi thời gian" "Ngày 15/06/2024 tôi lái ô tô vượt đèn đỏ"
