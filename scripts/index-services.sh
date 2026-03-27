#!/bin/bash
set -euo pipefail

DEFAULT_SERVICES=(ultron-activity ultron-api ultron-basic ultron-room ultron-doc)

usage() {
  cat <<'EOF'
Batch-index multiple service directories into the knowledge base.

Usage:
  index-services.sh --base-dir DIR [options] [SERVICE ...]

Required:
  --base-dir DIR     Base path containing one subdirectory per service name
                     (e.g. DIR/ultron-api). Each service indexes DIR/<name>.

Options:
  --kb-url URL       Knowledge base API base URL (default: $KB_URL or http://localhost:8100)
  --kb-token TOKEN   Bearer token for Authorization (default: $KB_TOKEN)
  --mode MODE        Indexing mode: full or incremental (default: full)
  --dry-run          Print curl commands only; do not call the API
  -h, --help         Show this help and exit

Positional:
  SERVICE ...        Service/repository names to index. If omitted, uses:
                     ultron-activity ultron-api ultron-basic ultron-room ultron-doc

Behavior:
  - For each service, POST /api/v1/index with JSON:
    {"directory":"<BASE_DIR>/<SERVICE>","mode":"<MODE>","repository":"<SERVICE>"}
  - Skips services whose directory does not exist (warning only).
  - Exits with status 1 if any HTTP request fails.

Environment:
  KB_URL, KB_TOKEN   Defaults when --kb-url / --kb-token are omitted.

Examples:
  # Index default services under ~/repos
  index-services.sh --base-dir ~/repos

  # Explicit URL and token
  index-services.sh --base-dir /data/src --kb-url https://kb.example.com --kb-token "$KB_TOKEN"

  # Incremental update for two services
  index-services.sh --base-dir /work --mode incremental ultron-api ultron-doc

  # Preview requests
  index-services.sh --dry-run --base-dir /tmp --kb-token test-token
EOF
}

error_missing_base_dir() {
  echo "error: --base-dir is required (use --help for usage)." >&2
  exit 1
}

json_body() {
  local dir="$1"
  local mode="$2"
  local repo="$3"
  python3 -c 'import json,sys; print(json.dumps({"directory":sys.argv[1],"mode":sys.argv[2],"repository":sys.argv[3]}))' "$dir" "$mode" "$repo"
}

BASE_DIR=""
KB_URL_VAL="${KB_URL:-http://localhost:8100}"
KB_TOKEN_VAL="${KB_TOKEN:-}"
MODE="full"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-dir)
      [[ $# -lt 2 ]] && { echo "error: --base-dir requires a value." >&2; exit 1; }
      BASE_DIR="$2"
      shift 2
      ;;
    --kb-url)
      [[ $# -lt 2 ]] && { echo "error: --kb-url requires a value." >&2; exit 1; }
      KB_URL_VAL="$2"
      shift 2
      ;;
    --kb-token)
      [[ $# -lt 2 ]] && { echo "error: --kb-token requires a value." >&2; exit 1; }
      KB_TOKEN_VAL="$2"
      shift 2
      ;;
    --mode)
      [[ $# -lt 2 ]] && { echo "error: --mode requires a value." >&2; exit 1; }
      MODE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

SERVICES=("$@")
if [[ ${#SERVICES[@]} -eq 0 ]]; then
  SERVICES=("${DEFAULT_SERVICES[@]}")
fi

if [[ -z "$BASE_DIR" ]]; then
  error_missing_base_dir
fi

if [[ "$MODE" != "full" && "$MODE" != "incremental" ]]; then
  echo "error: --mode must be 'full' or 'incremental' (got: $MODE)." >&2
  exit 1
fi

BASE_DIR="${BASE_DIR%/}"

ENDPOINT="${KB_URL_VAL%/}/api/v1/index"
FAILURES=0

for svc in "${SERVICES[@]}"; do
  dir="${BASE_DIR}/${svc}"
  echo "[${svc}] Indexing (${MODE})..."

  if [[ ! -d "$dir" ]]; then
    echo "warning: directory does not exist, skipping: $dir" >&2
    continue
  fi

  body="$(json_body "$dir" "$MODE" "$svc")"

  curl_cmd=(
    curl -fsS -X POST "$ENDPOINT"
    -H "Content-Type: application/json"
    -H "Authorization: Bearer ${KB_TOKEN_VAL}"
    -d "$body"
  )

  if [[ "$DRY_RUN" == true ]]; then
    printf 'dry-run: '
    printf '%q ' "${curl_cmd[@]}"
    echo
    continue
  fi

  if ! "${curl_cmd[@]}"; then
    echo "error: indexing failed for service: $svc" >&2
    FAILURES=$((FAILURES + 1))
  fi
done

if [[ "$FAILURES" -gt 0 ]]; then
  echo "error: $FAILURES service(s) failed to index." >&2
  exit 1
fi

exit 0
