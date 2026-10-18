#!/usr/bin/env bash
# Idempotent launcher: starts a 60-s outer loop around ensure_flywheel_watch.sh if it isn't running, then one pass. READ-ONLY.
s="$(cd "$(dirname "$0")" && pwd)/ensure_flywheel_watch.sh"
if pgrep -f "while true; do sleep 60; bash $s" >/dev/null; then echo "loop running: $s"; else
  setsid nohup bash -c "while true; do sleep 60; bash $s >/dev/null 2>&1; done" >/dev/null 2>&1 < /dev/null & echo "loop started (pid $!)"; fi
bash "$s"
