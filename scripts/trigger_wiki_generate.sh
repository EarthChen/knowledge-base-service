#!/usr/bin/env bash
set -euo pipefail

# Configuration
API_BASE="${API_BASE:-http://172.18.228.71:8100}"
AUTH_TOKEN="${AUTH_TOKEN:-sk-admin-test}"
BUSINESS_ID="${BUSINESS_ID:-default}"
LANGUAGE="${LANGUAGE:-zh}"
INCREMENTAL="${INCREMENTAL:-false}"
MODE="${MODE:-full}"
TIMEOUT="${TIMEOUT:-30}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
MAX_POLL="${MAX_POLL:-120}"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Trigger wiki generation and optionally poll task status.

Options:
  --business-id ID    Business ID (default: $BUSINESS_ID)
  --language LANG     Language: en|zh (default: $LANGUAGE)
  --incremental       Use incremental mode (default: full rebuild)
  --mode MODE         Generation mode: structure|full (default: $MODE)
  --api-base URL      API base URL (default: $API_BASE)
  --token TOKEN       Auth token (default: \$AUTH_TOKEN)
  --no-poll           Don't poll task status after triggering
  --poll-interval N   Poll interval in seconds (default: $POLL_INTERVAL)
  --max-poll N        Max poll duration in seconds (default: $MAX_POLL)
  -h, --help          Show this help
EOF
  exit 0
}

DO_POLL=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --business-id)   BUSINESS_ID="$2"; shift 2 ;;
    --language)      LANGUAGE="$2"; shift 2 ;;
    --incremental)   INCREMENTAL=true; shift ;;
    --mode)          MODE="$2"; shift 2 ;;
    --api-base)      API_BASE="$2"; shift 2 ;;
    --token)         AUTH_TOKEN="$2"; shift 2 ;;
    --no-poll)       DO_POLL=false; shift ;;
    --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
    --max-poll)      MAX_POLL="$2"; shift 2 ;;
    -h|--help)       usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

AUTH_HEADER="Authorization: Bearer ${AUTH_TOKEN}"

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Wiki Generation Trigger${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  API:          ${API_BASE}"
echo -e "  Business:     ${BUSINESS_ID}"
echo -e "  Language:     ${LANGUAGE}"
echo -e "  Incremental:  ${INCREMENTAL}"
echo -e "  Mode:         ${MODE}"

# Step 1: Health check
echo -e "\n${GREEN}[1/3]${NC} Checking service health..."
HEALTH=$(curl -s -m "$TIMEOUT" "${API_BASE}/api/v1/health" 2>&1) || {
  echo -e "  ${RED}✗${NC}  Service unreachable at ${API_BASE}"
  exit 1
}
STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
if [ "$STATUS" = "ok" ]; then
  echo -e "  ${GREEN}✓${NC}  Service healthy"
else
  echo -e "  ${YELLOW}⚠${NC}  Service status: ${STATUS}"
  echo "  Response: ${HEALTH}"
fi

# Step 2: Trigger wiki generation
echo -e "\n${GREEN}[2/3]${NC} Triggering wiki generation..."
BODY=$(cat <<EOF
{
  "business_id": "${BUSINESS_ID}",
  "language": "${LANGUAGE}",
  "incremental": ${INCREMENTAL},
  "mode": "${MODE}"
}
EOF
)

RESPONSE=$(curl -s -m "$TIMEOUT" -w "\n%{http_code}" \
  -X POST \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  "${API_BASE}/api/v1/wiki/business/generate" 2>&1)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
RESPONSE_BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "202" ]; then
  TASK_ID=$(echo "$RESPONSE_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null || echo "")
  echo -e "  ${GREEN}✓${NC}  Task accepted (HTTP 202)"
  echo -e "  Task ID: ${TASK_ID}"
elif [ "$HTTP_CODE" = "409" ]; then
  echo -e "  ${YELLOW}⚠${NC}  Generation already in progress (HTTP 409)"
  echo "  $RESPONSE_BODY"
  exit 0
else
  echo -e "  ${RED}✗${NC}  Failed (HTTP ${HTTP_CODE})"
  echo "  $RESPONSE_BODY"
  exit 1
fi

# Step 3: Poll task status
if [ "$DO_POLL" = false ] || [ -z "$TASK_ID" ]; then
  echo -e "\n${CYAN}Done. Check task status:${NC}"
  echo "  curl -s -H '${AUTH_HEADER}' ${API_BASE}/api/v1/wiki/tasks/active"
  exit 0
fi

echo -e "\n${GREEN}[3/3]${NC} Polling task status (interval=${POLL_INTERVAL}s, max=${MAX_POLL}s)..."
ELAPSED=0
while [ "$ELAPSED" -lt "$MAX_POLL" ]; do
  TASK_RESP=$(curl -s -m "$TIMEOUT" \
    -H "$AUTH_HEADER" \
    "${API_BASE}/api/v1/wiki/tasks/${TASK_ID}" 2>&1)

  TASK_STATUS=$(echo "$TASK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
  TASK_PROGRESS=$(echo "$TASK_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('progress_pct',0):.0%}\")" 2>/dev/null || echo "?")
  TASK_PHASE=$(echo "$TASK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('phase',''))" 2>/dev/null || echo "")

  case "$TASK_STATUS" in
    completed)
      echo -e "  ${GREEN}✓${NC}  Completed! (${ELAPSED}s elapsed)"
      PAGES=$(echo "$TASK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('pages_generated',0))" 2>/dev/null || echo "?")
      echo -e "  Pages generated: ${PAGES}"
      break
      ;;
    failed)
      echo -e "  ${RED}✗${NC}  Failed! (${ELAPSED}s elapsed)"
      ERROR=$(echo "$TASK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error',''))" 2>/dev/null || echo "")
      echo "  Error: ${ERROR}"
      exit 1
      ;;
    pending|running|in_progress)
      printf "  [%3ds] Status: %-12s Phase: %-25s Progress: %s\r" "$ELAPSED" "$TASK_STATUS" "$TASK_PHASE" "$TASK_PROGRESS"
      ;;
    *)
      echo -e "  ${YELLOW}?${NC}  Unknown status: ${TASK_STATUS} (${ELAPSED}s)"
      ;;
  esac

  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ "$ELAPSED" -ge "$MAX_POLL" ]; then
  echo -e "\n  ${YELLOW}⚠${NC}  Poll timeout (${MAX_POLL}s). Task may still be running."
  echo -e "  Check manually: curl -s -H '${AUTH_HEADER}' ${API_BASE}/api/v1/wiki/tasks/${TASK_ID}"
fi

echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
