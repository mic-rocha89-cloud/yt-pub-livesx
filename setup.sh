#!/usr/bin/env bash
# setup.sh — atalho para scripts/setup-system
# (Parte 1 do setup: prepara maquina + sobe master-dashboard)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/scripts/setup-system" "$@"
