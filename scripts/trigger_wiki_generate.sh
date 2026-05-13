#!/usr/bin/env bash
set -euo pipefail

# Configuration
API_BASE="${API_BASE:-http://172.18.228.71:8100}"
AUTH_TOKEN="${AUTH_TOKEN:-sk-admin-test}"
BUSINESS_ID="${BUSINESS_ID:-ultron}"
LANGUAGE="${WIKI_LANGUAGE:-zh}"
INCREMENTAL="${INCREMENTAL:-false}"
MODE="${MODE:-full}"
TIMEOUT="${TIMEOUT:-30}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
MAX_POLL="${MAX_POLL:-1800}"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

usage() {
  cat <<'USAGE'
Usage: trigger_wiki_generate.sh [OPTIONS] [COMMAND [ARGS...]]

Trigger wiki generation and monitor progress in real time.

Management commands (run API helpers; skip generation — put after common options):
  list-domains      List all domain anchors for the business
  move-module       Pin a module: move-module MODULE_NAME DOMAIN_SLUG
  unpin-module      Unpin a module: unpin-module MODULE_NAME
  reset-anchors     Delete all domain anchors (interactive confirm)
  checkpoint-info   Show LangGraph checkpoint status for the business
  checkpoint-delete Remove checkpoint SQLite data for the business
  resume            Resume wiki generation in incremental mode
  regenerate-domain Regenerate a specific domain: regenerate-domain DOMAIN_SLUG
  clean-wiki        Delete all wiki data + checkpoint (preserves code index)
  clean-regenerate  Clean all wiki data + checkpoint, then trigger full rebuild

Monitoring modes (pick one, default: --poll):
  --poll              Poll task status via REST API (default)
  --stream            Stream SSE events in real time (Ctrl-C to stop)
  --no-poll           Fire and forget — just trigger, don't monitor

Common options:
  --business-id ID    Business ID              (default: ultron)
  --language LANG     Language: en|zh           (default: zh)
  --incremental       Incremental mode         (default: full rebuild)
  --mode MODE         structure|full            (default: full)
  --api-base URL      API base URL
  --token TOKEN       Auth token
  --poll-interval N   Seconds between polls    (default: 10)
  --max-poll N        Max poll duration seconds (default: 1800)
  --task-id ID        Skip trigger, attach to existing task
  -h, --help          Show this help
USAGE
  exit 0
}

WATCH_MODE="poll"   # poll | stream | none
ATTACH_TASK_ID=""
MGMT_CMD=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --business-id)   BUSINESS_ID="$2"; shift 2 ;;
    --language)      LANGUAGE="$2"; shift 2 ;;
    --incremental)   INCREMENTAL=true; shift ;;
    --mode)          MODE="$2"; shift 2 ;;
    --api-base)      API_BASE="$2"; shift 2 ;;
    --token)         AUTH_TOKEN="$2"; shift 2 ;;
    --no-poll)       WATCH_MODE="none"; shift ;;
    --poll)          WATCH_MODE="poll"; shift ;;
    --stream)        WATCH_MODE="stream"; shift ;;
    --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
    --max-poll)      MAX_POLL="$2"; shift 2 ;;
    --task-id)       ATTACH_TASK_ID="$2"; shift 2 ;;
    list-domains|move-module|unpin-module|reset-anchors|checkpoint-info|checkpoint-delete|resume|regenerate-domain|clean-wiki|clean-regenerate)
      MGMT_CMD="$1"
      shift
      break
      ;;
    -h|--help)       usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

AUTH_HEADER="Authorization: Bearer ${AUTH_TOKEN}"

if [ -n "$MGMT_CMD" ]; then
  case "$MGMT_CMD" in
    list-domains)
      echo "Listing domains for business: ${BUSINESS_ID}"
      curl -s -m "$TIMEOUT" -H "$AUTH_HEADER" \
        "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/domains" | python3 -m json.tool
      ;;
    move-module)
      MODULE_NAME="${1:?Module name required}"
      DOMAIN_SLUG="${2:?Domain slug required}"
      shift 2
      echo "Pinning module ${MODULE_NAME} to domain ${DOMAIN_SLUG}"
      BODY=$(python3 -c "import json,sys; print(json.dumps({'module_name':sys.argv[1],'domain_slug':sys.argv[2]}))" "$MODULE_NAME" "$DOMAIN_SLUG")
      curl -s -m "$TIMEOUT" -X POST \
        -H "$AUTH_HEADER" \
        -H "Content-Type: application/json" \
        -d "$BODY" \
        "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/domains/pin-module" | python3 -m json.tool
      ;;
    unpin-module)
      MODULE_NAME="${1:?Module name required}"
      shift
      echo "Unpinning module ${MODULE_NAME}"
      BODY=$(python3 -c "import json,sys; print(json.dumps({'module_name':sys.argv[1]}))" "$MODULE_NAME")
      curl -s -m "$TIMEOUT" -X POST \
        -H "$AUTH_HEADER" \
        -H "Content-Type: application/json" \
        -d "$BODY" \
        "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/domains/unpin-module" | python3 -m json.tool
      ;;
    reset-anchors)
      echo "WARNING: This will delete ALL domain anchors for ${BUSINESS_ID}"
      read -r -p "Are you sure? (y/N) " -n 1 reply
      echo
      if [[ "${reply}" =~ ^[Yy]$ ]]; then
        DOMAINS=$(curl -s -m "$TIMEOUT" -H "$AUTH_HEADER" \
          "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/domains" \
          | python3 -c "import sys,json; d=json.load(sys.stdin); [print(x.get('slug','')) for x in d.get('domains',[]) if x.get('slug')]")
        while IFS= read -r slug; do
          [ -z "$slug" ] && continue
          echo "  Deleting domain: ${slug}"
          curl -s -m "$TIMEOUT" -H "$AUTH_HEADER" \
            -X DELETE "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/domains/${slug}"
          echo
        done <<< "${DOMAINS}"
        echo "All anchors reset."
      else
        echo "Cancelled."
      fi
      ;;
    checkpoint-info)
      echo "Checkpoint info for business: ${BUSINESS_ID}"
      curl -s -m "$TIMEOUT" -H "$AUTH_HEADER" \
        "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/checkpoint" | python3 -m json.tool
      ;;
    checkpoint-delete)
      echo "Deleting checkpoint for business: ${BUSINESS_ID}"
      curl -s -m "$TIMEOUT" -H "$AUTH_HEADER" \
        -X DELETE "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/checkpoint" | python3 -m json.tool
      ;;
    resume)
      echo "Resuming wiki generation (incremental) for business: ${BUSINESS_ID}"
      BODY=$(python3 -c "import json,sys; print(json.dumps({'business_id':sys.argv[1],'language':sys.argv[2],'incremental':True,'mode':'full'}))" "$BUSINESS_ID" "$LANGUAGE")
      curl -s -m "$TIMEOUT" -X POST \
        -H "$AUTH_HEADER" \
        -H "Content-Type: application/json" \
        -d "$BODY" \
        "${API_BASE}/api/v1/wiki/business/generate" | python3 -m json.tool
      ;;
    regenerate-domain)
      DOMAIN_SLUG="${1:?Domain slug required}"
      shift
      echo "Regenerating domain: ${DOMAIN_SLUG} for business: ${BUSINESS_ID}"
      BODY=$(python3 -c "import json,sys; print(json.dumps({'business_id':sys.argv[1],'language':sys.argv[2],'domain_slug':sys.argv[3],'mode':'full'}))" "$BUSINESS_ID" "$LANGUAGE" "$DOMAIN_SLUG")
      curl -s -m "$TIMEOUT" -X POST \
        -H "$AUTH_HEADER" \
        -H "Content-Type: application/json" \
        -d "$BODY" \
        "${API_BASE}/api/v1/wiki/business/generate" | python3 -m json.tool
      ;;
    clean-wiki)
      echo -e "${YELLOW}WARNING: This will delete ALL wiki data + checkpoint for ${BUSINESS_ID}${NC}"
      echo "  (Code index will be preserved)"
      read -r -p "Are you sure? (y/N) " -n 1 reply
      echo
      if [[ "${reply}" =~ ^[Yy]$ ]]; then
        echo "Deleting wiki data..."
        curl -s -m "$TIMEOUT" -X DELETE \
          -H "$AUTH_HEADER" -H "X-Business-Id: ${BUSINESS_ID}" \
          "${API_BASE}/api/v1/wiki/${BUSINESS_ID}" | python3 -m json.tool
        echo "Deleting checkpoint..."
        curl -s -m "$TIMEOUT" -X DELETE \
          -H "$AUTH_HEADER" -H "X-Business-Id: ${BUSINESS_ID}" \
          "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/checkpoint" | python3 -m json.tool
        echo -e "${GREEN}Wiki data cleaned.${NC}"
      else
        echo "Cancelled."
      fi
      ;;
    clean-regenerate)
      echo -e "${YELLOW}WARNING: This will delete ALL wiki data + checkpoint for ${BUSINESS_ID}, then trigger full rebuild${NC}"
      read -r -p "Are you sure? (y/N) " -n 1 reply
      echo
      if [[ "${reply}" =~ ^[Yy]$ ]]; then
        echo "Deleting wiki data..."
        DEL_RESULT=$(curl -s -m "$TIMEOUT" -X DELETE \
          -H "$AUTH_HEADER" -H "X-Business-Id: ${BUSINESS_ID}" \
          "${API_BASE}/api/v1/wiki/${BUSINESS_ID}")
        DELETED=$(echo "$DEL_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('deleted_nodes',0))" 2>/dev/null || echo "?")
        echo "  Deleted ${DELETED} wiki nodes"
        echo "Deleting checkpoint..."
        curl -s -m "$TIMEOUT" -X DELETE \
          -H "$AUTH_HEADER" -H "X-Business-Id: ${BUSINESS_ID}" \
          "${API_BASE}/api/v1/wiki/${BUSINESS_ID}/checkpoint" > /dev/null 2>&1
        echo "  Checkpoint deleted"
        echo ""
        echo "Triggering full wiki rebuild..."
        INCREMENTAL=false
        MGMT_CMD=""
      else
        echo "Cancelled."
        exit 0
      fi
      ;;
  esac
  # clean-regenerate falls through to trigger generation
  if [ -n "$MGMT_CMD" ] && [ "$MGMT_CMD" != "clean-regenerate" ]; then
    exit 0
  fi
fi

ts() { date '+%H:%M:%S'; }

# ── Inline Python helper (parses JSON once, outputs tab-separated fields) ──
read_task_fields() {
  python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print('error\t\t\t\t\t\t')
    sys.exit(0)
status       = d.get('status', 'unknown')
phase        = d.get('phase', '')
pct          = d.get('progress_pct', '')
current_repo = d.get('current_repo', '')
completed    = d.get('completed_repos', '')
total        = d.get('total_repos', '')
detail       = d.get('detail', '')
print(f'{status}\t{phase}\t{pct}\t{current_repo}\t{completed}\t{total}\t{detail}')
"
}

# ── Header ──
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Wiki Generation Monitor${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  API:          ${API_BASE}"
echo -e "  Business:     ${BUSINESS_ID}"
echo -e "  Language:     ${LANGUAGE}"
echo -e "  Incremental:  ${INCREMENTAL}"
echo -e "  Mode:         ${MODE}"
echo -e "  Watch:        ${WATCH_MODE}"

# ── Step 1: Health check ──
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

# ── Step 2: Trigger or attach ──
if [ -n "$ATTACH_TASK_ID" ]; then
  TASK_ID="$ATTACH_TASK_ID"
  echo -e "\n${GREEN}[2/3]${NC} Attaching to existing task: ${TASK_ID}"
else
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
fi

# ── Step 3: Watch progress ──
if [ "$WATCH_MODE" = "none" ] || [ -z "$TASK_ID" ]; then
  echo -e "\n${CYAN}Done. Monitor later with:${NC}"
  echo "  $0 --task-id ${TASK_ID} --no-poll"
  echo "  $0 --task-id ${TASK_ID} --stream"
  exit 0
fi

# ────────────────────────────────────────────────────────
#  Mode A: SSE real-time event stream
# ────────────────────────────────────────────────────────
if [ "$WATCH_MODE" = "stream" ]; then
  echo -e "\n${GREEN}[3/3]${NC} Streaming SSE events (Ctrl-C to stop)..."
  echo -e "${DIM}─────────────────────────────────────────────────────${NC}"
  curl -s -N \
    -H "$AUTH_HEADER" \
    "${API_BASE}/api/v1/wiki/events?business_id=${BUSINESS_ID}" 2>&1 \
  | while IFS= read -r line; do
      # SSE lines: "data: {...}" or ": keepalive"
      case "$line" in
        "data: "*)
          payload="${line#data: }"
          # Pretty-print key fields
          python3 -c "
import sys, json
try:
    d = json.loads(sys.argv[1])
except Exception:
    print(sys.argv[1])
    sys.exit(0)
etype = d.get('type', '?')
ts    = d.get('timestamp', '')[:19]
path  = d.get('page_path', '')
pl    = d.get('payload', {})
tid   = pl.get('task_id', '')
parts = [f'[{ts}] {etype}']
if tid:  parts.append(f'task={tid}')
if path: parts.append(f'page={path}')
extras = {k:v for k,v in pl.items() if k not in ('task_id',)}
if extras: parts.append(json.dumps(extras, ensure_ascii=False))
print('  '.join(parts))
" "$payload"
          ;;
        ": keepalive"*|": stream-open"*)
          ;;
        *)
          [ -n "$line" ] && echo -e "  ${DIM}${line}${NC}"
          ;;
      esac
    done
  exit 0
fi

# ────────────────────────────────────────────────────────
#  Mode B: REST polling with detailed progress
# ────────────────────────────────────────────────────────
echo -e "\n${GREEN}[3/3]${NC} Polling task status (interval=${POLL_INTERVAL}s, max=${MAX_POLL}s)..."
echo -e "${DIM}  Endpoint: /api/v1/wiki/business/tasks/${TASK_ID}${NC}"
echo -e "${DIM}─────────────────────────────────────────────────────${NC}"

ELAPSED=0
PREV_LINE=""
while [ "$ELAPSED" -lt "$MAX_POLL" ]; do
  TASK_RESP=$(curl -s -m "$TIMEOUT" \
    -H "$AUTH_HEADER" \
    "${API_BASE}/api/v1/wiki/business/tasks/${TASK_ID}" 2>&1)

  IFS=$'\t' read -r T_STATUS T_PHASE T_PCT T_REPO T_DONE T_TOTAL T_DETAIL \
    <<< "$(echo "$TASK_RESP" | read_task_fields)"

  NOW=$(ts)

  case "$T_STATUS" in
    completed)
      echo ""
      echo -e "  ${GREEN}✓${NC}  [${NOW}] Completed! (${ELAPSED}s elapsed)"
      echo "$TASK_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('result', d)
if isinstance(r, str):
    import json as j
    try: r = j.loads(r)
    except: pass
if isinstance(r, dict):
    for k in ('pages_count','pages_generated','partial_errors','skipped_repos'):
        v = r.get(k)
        if v is not None:
            print(f'  {k}: {v}')
"
      break
      ;;
    failed|cancelled)
      echo ""
      echo -e "  ${RED}✗${NC}  [${NOW}] ${T_STATUS}! (${ELAPSED}s elapsed)"
      echo "$TASK_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for k in ('error','detail','partial_errors'):
    v = d.get(k)
    if v: print(f'  {k}: {v}')
"
      exit 1
      ;;
    pending|running|in_progress)
      PROGRESS_BAR=""
      if [ -n "$T_PCT" ] && [ "$T_PCT" != "0" ]; then
        PROGRESS_BAR=" ${T_PCT}%"
      fi

      REPO_INFO=""
      if [ -n "$T_DONE" ] && [ -n "$T_TOTAL" ] && [ "$T_TOTAL" != "0" ]; then
        REPO_INFO=" [${T_DONE}/${T_TOTAL}]"
      fi

      CUR_REPO=""
      if [ -n "$T_REPO" ]; then
        CUR_REPO=" repo=${T_REPO}"
      fi

      PHASE_STR=""
      if [ -n "$T_PHASE" ]; then
        PHASE_STR=" phase=${T_PHASE}"
      fi

      DETAIL_STR=""
      if [ -n "$T_DETAIL" ]; then
        DETAIL_STR=" | ${T_DETAIL}"
      fi

      CUR_LINE="${T_STATUS}${PROGRESS_BAR}${REPO_INFO}${PHASE_STR}${CUR_REPO}${DETAIL_STR}"

      if [ "$CUR_LINE" != "$PREV_LINE" ]; then
        echo -e "  ${DIM}[${NOW}]${NC} ${T_STATUS}${GREEN}${PROGRESS_BAR}${NC}${REPO_INFO}${CYAN}${PHASE_STR}${NC}${CUR_REPO}${DIM}${DETAIL_STR}${NC}"
        PREV_LINE="$CUR_LINE"
      fi
      ;;
    *)
      echo -e "  ${YELLOW}?${NC}  [${NOW}] Unknown status: ${T_STATUS}"
      ;;
  esac

  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ "$ELAPSED" -ge "$MAX_POLL" ]; then
  echo -e "\n  ${YELLOW}⚠${NC}  Poll timeout (${MAX_POLL}s). Task may still be running."
  echo -e "  Resume monitoring:"
  echo -e "    $0 --task-id ${TASK_ID}"
  echo -e "    $0 --task-id ${TASK_ID} --stream"
fi

echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
