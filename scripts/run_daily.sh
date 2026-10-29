#!/usr/bin/env bash
# Cron entry point: runs job-radar from the repo root and keeps data/run.log small.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG=data/run.log
# keep roughly the last 2000 lines
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 4000 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ===" >> "$LOG"
.venv/bin/python -m jobradar run >> "$LOG" 2>&1
