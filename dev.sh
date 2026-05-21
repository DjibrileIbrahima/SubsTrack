#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${CYAN}[dev]${NC} $*"; }
warn() { echo -e "${YELLOW}[dev]${NC} $*"; }
err()  { echo -e "${RED}[dev]${NC} $*"; exit 1; }

# ── cleanup on exit ───────────────────────────────────────────────────────────

cleanup() {
    echo ""
    warn "Shutting down..."
    [ -n "${BACKEND_PID:-}"  ] && kill "$BACKEND_PID"  2>/dev/null || true
    [ -n "${WORKER_PID:-}"   ] && kill "$WORKER_PID"   2>/dev/null || true
    [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    wait "${BACKEND_PID:-}"  2>/dev/null || true
    wait "${WORKER_PID:-}"   2>/dev/null || true
    wait "${FRONTEND_PID:-}" 2>/dev/null || true
    echo -e "${GREEN}[dev]${NC} Done."
}
trap cleanup EXIT INT TERM

# ── preflight ─────────────────────────────────────────────────────────────────

[ -f "$BACKEND/.env" ] || err "backend/.env not found — copy .env.example and fill in your secrets."

if [ ! -d "$FRONTEND/node_modules" ]; then
    warn "node_modules missing — running npm install..."
    npm --prefix "$FRONTEND" install
fi

# ── resolve system python ─────────────────────────────────────────────────────

SYS_PYTHON="$(command -v python || command -v python3 || true)"
[ -n "$SYS_PYTHON" ] || err "Python not found. Install Python 3.10+ and try again."

# ── create venv if missing ────────────────────────────────────────────────────

VENV="$ROOT/.venv"
if [ ! -f "$VENV/Scripts/python.exe" ] && [ ! -f "$VENV/bin/python" ]; then
    log "Creating virtual environment at .venv ..."
    "$SYS_PYTHON" -m venv "$VENV"
fi

# Detect WSL (Linux kernel with "microsoft" in its name)
IS_WSL=false
[[ "$(uname -r 2>/dev/null)" == *microsoft* ]] && IS_WSL=true

# Resolve any venv binary correctly on Windows (Scripts/*.exe) or Unix (bin/*)
if [ -f "$VENV/Scripts/python.exe" ]; then
    venv_bin() { echo "$VENV/Scripts/$1.exe"; }
    # Windows .exe binaries need Windows-style paths when called from WSL
    win_path() { $IS_WSL && wslpath -w "$1" || echo "$1"; }
else
    venv_bin() { echo "$VENV/bin/$1"; }
    win_path() { echo "$1"; }
fi

PYTHON="$(venv_bin python)"
UVICORN="$(venv_bin uvicorn)"
PIP="$(venv_bin pip)"

# ── install / sync requirements ───────────────────────────────────────────────

log "Checking Python requirements..."
"$PIP" install -q -r "$(win_path "$BACKEND/requirements.txt")"
log "Requirements up to date."

command -v docker &>/dev/null || err "Docker not found. Install Docker Desktop and try again."

# ── start Docker containers ───────────────────────────────────────────────────

log "Starting Docker containers (Postgres + Redis)..."
docker compose -f "$ROOT/docker-compose.dev.yml" --env-file "$BACKEND/.env" up -d

# Wait until Postgres accepts connections
log "Waiting for Postgres to be ready..."
for i in $(seq 1 20); do
    if docker exec substrack_db pg_isready -U substrack &>/dev/null 2>&1; then
        log "Postgres is ready."
        break
    fi
    [ "$i" -eq 20 ] && err "Postgres did not become ready in time."
    sleep 1
done

# ── start backend ─────────────────────────────────────────────────────────────

log "Starting backend  →  http://localhost:8000"
cd "$BACKEND"
"$UVICORN" main:app --reload --host 0.0.0.0 --port 8000 2>&1 \
    | sed $'s/^/\033[0;32m[backend]\033[0m /' &
BACKEND_PID=$!

# ── start ARQ worker ──────────────────────────────────────────────────────────

log "Starting ARQ worker"
cd "$BACKEND"
"$PYTHON" -m arq worker.WorkerSettings 2>&1 \
    | sed $'s/^/\033[0;35m[worker]\033[0m /' &
WORKER_PID=$!

# ── start frontend ────────────────────────────────────────────────────────────

log "Starting frontend →  http://localhost:5173"
cd "$FRONTEND"
npm run dev 2>&1 \
    | sed $'s/^/\033[1;33m[frontend]\033[0m /' &
FRONTEND_PID=$!

# ── ready ─────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}All services running.${NC}"
echo -e "  Backend  →  http://localhost:8000"
echo -e "  API docs →  http://localhost:8000/docs"
echo -e "  Frontend →  http://localhost:5173"
echo -e "\nPress ${YELLOW}Ctrl+C${NC} to stop everything.\n"

wait "$BACKEND_PID" "$WORKER_PID" "$FRONTEND_PID"
