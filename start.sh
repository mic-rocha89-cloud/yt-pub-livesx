#!/usr/bin/env bash
# start.sh — Inicia dashboard + scheduler do yt-pub-lives
set -euo pipefail

PORT="${1:-8090}"
DIR="$(cd "$(dirname "$0")" && pwd)"

export PATH="/usr/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$HOME/google-cloud-sdk/bin:$PATH"

# Mata instancias anteriores
fuser -k "$PORT/tcp" 2>/dev/null || true
pkill -f "python3 $DIR/scheduler.py" 2>/dev/null || true
sleep 1

# Inicia scheduler em background
echo "==> Scheduler iniciado (log: /tmp/yt-scheduler.log)"
python3 "$DIR/scheduler.py" > /tmp/yt-scheduler.log 2>&1 &
SCHED_PID=$!

# Inicia dashboard (foreground)
echo "==> Dashboard: http://localhost:$PORT"
echo "==> Para parar: Ctrl+C"
echo ""

cleanup() {
  echo ""
  echo "==> Parando scheduler (PID $SCHED_PID)..."
  kill $SCHED_PID 2>/dev/null || true
  echo "==> Encerrado."
}
trap cleanup EXIT

cd "$DIR/dashboard" && python3 server.py "$PORT"
