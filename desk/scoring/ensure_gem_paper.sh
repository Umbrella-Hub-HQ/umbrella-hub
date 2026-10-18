#!/usr/bin/env bash
# Single-instance supervisor for gem_paper.py (PAPER ONLY). Restarts it if its pid is gone or gem_status.json heartbeat > 180 s old.
# Kills ONLY the pid recorded in gem_paper.pid after confirming /proc cmdline is this gem_paper.py (no name-based kills).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE" || exit 1
exec 9>"$HERE/.gem_paper_ensure.lock"; flock -n 9 || exit 0
PIDFILE=gem_paper.pid
AGE=$(python3 -c 'import json,datetime as D;s=json.load(open("gem_status.json"));print(int((D.datetime.now(D.timezone.utc)-D.datetime.fromisoformat(s["heartbeat"])).total_seconds()))' 2>/dev/null || echo 99999)
PID=$(tr -dc '0-9' < "$PIDFILE" 2>/dev/null)
is_ours(){ [ -n "$1" ] && [ -r "/proc/$1/cmdline" ] && tr '\0' ' ' < "/proc/$1/cmdline" | grep -Eq 'python3?[^ ]* +(\S*/)?gem_paper\.py( |$)'; }
if is_ours "$PID" && [ "$AGE" -le 180 ]; then echo "ok pid $PID heartbeat ${AGE}s"; exit 0; fi
if is_ours "$PID"; then kill "$PID" 2>/dev/null; sleep 1; fi
# paper250 2026-10-18: 9>&- so the child does not inherit (and hold forever) this script's flock; before this fix the
# supervisor exited at 'flock -n' while gem_paper lived, so the stale-heartbeat restart never ran.
setsid nohup python3 "$HERE/gem_paper.py" >> "$HERE/gem_paper.out" 2>&1 < /dev/null 9>&- &
echo $! > "$PIDFILE"
echo "$(date '+%F %T') ensure_gem_paper: started pid $! (old pid ${PID:-none}, heartbeat age ${AGE}s)" | tee -a gem_paper.log
