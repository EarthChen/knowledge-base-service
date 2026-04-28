#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
DEV_HOST="dev"
REMOTE_DIR="~/review-bot/knowledge-base-service"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_DIR="$LOCAL_DIR/dashboard"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

SKIP_BUILD=false
SKIP_RESTART=false
DRY_RUN=false

usage() {
  echo "Usage: $0 [--skip-build] [--skip-restart] [--dry-run] [-h|--help]"
  echo ""
  echo "Options:"
  echo "  --skip-build     Skip frontend build step"
  echo "  --skip-restart   Sync files only, do not restart the backend"
  echo "  --dry-run        Show rsync dry-run (no actual transfer)"
  echo "  -h, --help       Show this help"
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build)   SKIP_BUILD=true; shift ;;
    --skip-restart)  SKIP_RESTART=true; shift ;;
    --dry-run)       DRY_RUN=true; shift ;;
    -h|--help)       usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Deploy to Dev Machine ($DEV_HOST)${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── Step 1: Build frontend ──────────────────────────────────────
if [ "$SKIP_BUILD" = false ]; then
  echo -e "\n${GREEN}[1/4]${NC} Building frontend..."
  (cd "$DASHBOARD_DIR" && pnpm build)
  echo -e "  ${GREEN}✓${NC}  Frontend build complete"
else
  echo -e "\n${YELLOW}[1/4]${NC} Skipping frontend build (--skip-build)"
fi

# ── Step 2: rsync to dev (protecting .env, .venv, data) ─────────
echo -e "\n${GREEN}[2/4]${NC} Syncing files to ${DEV_HOST}:${REMOTE_DIR}..."

RSYNC_OPTS=(
  -avz
  --delete
  --exclude='.env'
  --exclude='.env.*'
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.git/'
  --exclude='node_modules/'
  --exclude='dashboard/node_modules/'
  --exclude='data/'
  --exclude='.pytest_cache/'
  --exclude='.mypy_cache/'
  --exclude='.ruff_cache/'
  --exclude='*.egg-info/'
  --exclude='.cursor/'
  --exclude='.claude/'
  --exclude='docs/superpowers/'
)

if [ "$DRY_RUN" = true ]; then
  RSYNC_OPTS+=(-n)
  echo -e "  ${YELLOW}(dry-run mode)${NC}"
fi

rsync "${RSYNC_OPTS[@]}" "$LOCAL_DIR/" "${DEV_HOST}:${REMOTE_DIR}/"
echo -e "  ${GREEN}✓${NC}  Sync complete"

# ── Step 3: Install/update deps on remote ────────────────────────
echo -e "\n${GREEN}[3/4]${NC} Updating dependencies on remote..."
ssh "$DEV_HOST" "export PATH=\"/opt/homebrew/bin:\$HOME/.local/bin:\$PATH\"; cd ${REMOTE_DIR} && source .venv/bin/activate && uv pip install -e '.[dev]' --quiet 2>&1 | tail -3"
echo -e "  ${GREEN}✓${NC}  Dependencies updated"

# ── Step 4: Restart backend ──────────────────────────────────────
if [ "$SKIP_RESTART" = false ]; then
  echo -e "\n${GREEN}[4/4]${NC} Restarting backend service..."
  REMOTE_PID=$(ssh "$DEV_HOST" "pgrep -f 'uvicorn main:app.*8100' || true")
  if [ -n "$REMOTE_PID" ]; then
    echo -e "  Stopping PID ${REMOTE_PID}..."
    ssh "$DEV_HOST" "kill $REMOTE_PID 2>/dev/null || true"
    sleep 2
    STILL_RUNNING=$(ssh "$DEV_HOST" "pgrep -f 'uvicorn main:app.*8100' || true")
    if [ -n "$STILL_RUNNING" ]; then
      echo -e "  ${YELLOW}Force killing...${NC}"
      ssh "$DEV_HOST" "kill -9 $STILL_RUNNING 2>/dev/null || true"
      sleep 1
    fi
    echo -e "  ${GREEN}✓${NC}  Old process stopped"
  else
    echo -e "  ${YELLOW}No running backend found${NC}"
  fi

  echo -e "  Starting backend..."
  ssh "$DEV_HOST" "cd ${REMOTE_DIR} && source .venv/bin/activate && nohup .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8100 > /tmp/kb-service.log 2>&1 &"
  sleep 3

  NEW_PID=$(ssh "$DEV_HOST" "pgrep -f 'uvicorn main:app.*8100' || true")
  if [ -n "$NEW_PID" ]; then
    echo -e "  ${GREEN}✓${NC}  Backend started (PID: ${NEW_PID})"
  else
    echo -e "  ${RED}✗${NC}  Backend may have failed to start. Check /tmp/kb-service.log"
    echo -e "  Run: ssh dev 'tail -50 /tmp/kb-service.log'"
  fi
else
  echo -e "\n${YELLOW}[4/4]${NC} Skipping restart (--skip-restart)"
fi

echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}Deploy complete!${NC}"
echo -e "  Backend: http://${DEV_HOST}:8100"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
