#!/usr/bin/env bash
# finish.sh — kept for compatibility; the real work is in finish.py.
#   bash <skill>/scripts/finish.sh <video-dir> [finish.py options]
set -euo pipefail
SK="$(cd "$(dirname "$0")/.." && pwd)"
source "$SK/scripts/env.sh"
exec "$EV2_PY" "$SK/scripts/finish.py" "$@"
