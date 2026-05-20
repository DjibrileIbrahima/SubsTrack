#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$ROOT/.venv"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    echo -e "${GREEN}Done.${NC}"
}
trap cleanup EXIT INT TERM

# ── preflight checks ──────────────────────────────────────────────────────────

if [ ! -f "$VENV/bin/python" ] && [ ! -f "$VENV/Scripts/python.exe" ]; then
    echo -e "${RED}Error:${NC} virtual environment not found at .venv/"
    echo "Run: python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"
    exit 1
fi

if [ ! -f "$BACKEND/.env" ]; then
    echo -e "${RED}Error:${NC} backend/.env not found — copy .env.example and fill in your secrets."
    exit 1
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
    echo -e "${YELLOW}node_modules not found — running npm install...${NC}"
    npm --prefix "$FRONTEND" install
fi

# ── activate venv ─────────────────────────────────────────────────────────────

if [ -f "$VENV/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
elif [ -f "$VENV/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV/Scripts/activate"
fi

# ── start backend ─────────────────────────────────────────────────────────────

echo -e "${GREEN}Starting backend${NC}  →  http://localhost:8000"
cd "$BACKEND"
uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 | sed "s/^/[${GREEN}backend${NC}] /" &
BACKEND_PID=$!

# ── start frontend ────────────────────────────────────────────────────────────

echo -e "${GREEN}Starting frontend${NC} →  http://localhost:5173"
cd "$FRONTEND"
npm run dev 2>&1 | sed "s/^/[${YELLOW}frontend${NC}] /" &
FRONTEND_PID=$!

# ── wait ──────────────────────────────────────────────────────────────────────

echo -e "\n${GREEN}Both services running.${NC} Press Ctrl+C to stop.\n"
wait "$BACKEND_PID" "$FRONTEND_PID"
