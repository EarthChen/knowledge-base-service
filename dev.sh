#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_DIR="$ROOT_DIR/dashboard"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

PIDS=()

cleanup() {
  echo ""
  echo -e "${YELLOW}⏹  Shutting down...${NC}"
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null
  echo -e "${GREEN}✓  All services stopped.${NC}"
}

trap cleanup EXIT INT TERM

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Knowledge Base Service — Dev Launcher${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# --- Step 1: FalkorDB (Docker) ---
echo -e "\n${GREEN}[1/3]${NC} Starting FalkorDB via Docker..."
if ! docker compose -f "$ROOT_DIR/docker-compose.yaml" ps --services --filter "status=running" 2>/dev/null | grep -q falkordb; then
  docker compose -f "$ROOT_DIR/docker-compose.yaml" up -d falkordb
  echo -e "  ${GREEN}✓${NC}  FalkorDB started (port 6379)"
else
  echo -e "  ${GREEN}✓${NC}  FalkorDB already running"
fi

# --- Step 2: Ensure Python venv ---
if [ ! -d "$ROOT_DIR/.venv" ]; then
  echo -e "\n${YELLOW}⚙  Python venv not found — creating...${NC}"
  (cd "$ROOT_DIR" && uv venv && uv pip install -e ".[dev]")
fi

# --- Step 3: Ensure Node modules ---
if [ ! -d "$DASHBOARD_DIR/node_modules" ]; then
  echo -e "\n${YELLOW}⚙  Node modules not found — installing...${NC}"
  (cd "$DASHBOARD_DIR" && pnpm install)
fi

# --- Step 4: Start Backend ---
echo -e "\n${GREEN}[2/3]${NC} Starting FastAPI backend (port 8100)..."
(cd "$ROOT_DIR" && uv run uvicorn main:app --host 0.0.0.0 --port 8100 --reload) &
PIDS+=($!)

# --- Step 5: Start Frontend Dev Server ---
echo -e "${GREEN}[3/3]${NC} Starting Vite dev server (port 5173)..."
(cd "$DASHBOARD_DIR" && pnpm dev) &
PIDS+=($!)

echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}Backend:${NC}    http://localhost:8100"
echo -e "  ${GREEN}Frontend:${NC}   http://localhost:5173"
echo -e "  ${GREEN}FalkorDB:${NC}   localhost:6379"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo ""

wait
