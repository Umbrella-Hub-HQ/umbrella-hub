#!/usr/bin/env bash
# Idempotent launcher (safe to run any number of times, e.g. after a reboot): starts a 60-s outer loop that calls
# ensure_tg_watch.sh if it is not already running, then runs one supervisor pass. READ-ONLY watcher.
s="$(cd "$(dirname "$0")" && pwd)/ensure_tg_watch.sh"
if pgrep -f "while true; do sleep 60; bash $s" >/dev/null; then echo "loop running: $s"; else
  setsid nohup bash -c "while true; do sleep 60; bash $s >/dev/null 2>&1; done" >/dev/null 2>&1 < /dev/null & echo "loop started (pid $!)"; fi
bash "$s"
