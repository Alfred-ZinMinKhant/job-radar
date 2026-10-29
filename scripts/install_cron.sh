#!/usr/bin/env bash
# Prints the crontab entry for job-radar and installs it only if you say yes.
# Usage: scripts/install_cron.sh [--evening]   (--evening adds an 18:00 run)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$ROOT/scripts/run_daily.sh"

LINES="# job-radar
CRON_TZ=Asia/Bangkok
30 8 * * * \"$ROOT/scripts/run_daily.sh\""
if [ "${1:-}" = "--evening" ]; then
  LINES="$LINES
0 18 * * * \"$ROOT/scripts/run_daily.sh\""
fi

echo "This will be added to your crontab:"
echo
echo "$LINES"
echo
echo "Note: CRON_TZ is honoured by Linux cron (cronie/Vixie). macOS cron ignores it,"
echo "so there the times follow the Mac's own clock; set the Mac to Bangkok time."
echo "Also, the machine must be awake at that time (a sleeping laptop skips the run)."
echo
read -r -p "Install? [y/N] " ans
[ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "Nothing changed."; exit 0; }

CURRENT="$(crontab -l 2>/dev/null | grep -v -e '# job-radar' -e 'run_daily.sh' -e '^CRON_TZ=Asia/Bangkok$' || true)"
printf '%s\n%s\n' "$CURRENT" "$LINES" | sed '/./,$!d' | crontab -
echo "Installed. Check with: crontab -l"
