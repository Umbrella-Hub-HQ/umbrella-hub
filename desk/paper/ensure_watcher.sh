#!/usr/bin/env bash
# Restart adaptive_watcher.py (PAPER ONLY) if it's not running or its heartbeat is older than 3 min.
# Does not restart if the watcher exited because no positions are open.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE" || exit 1
ST=watcher_status.json
if [ -f "$ST" ] && grep -q EXITED_NO_POSITIONS "$ST" && ! python3 -c 'import json,sys;b=json.load(open("paper_book.json"));sys.exit(0 if any(p["qty_open"]>1e-12 for p in b["positions"]) else 1)'; then echo "no open positions; not restarting"; exit 0; fi
AGE=$(python3 -c 'import json,datetime as D;s=json.load(open("watcher_status.json"));print(int((D.datetime.now(D.timezone.utc)-D.datetime.fromisoformat(s["heartbeat"])).total_seconds()))' 2>/dev/null || echo 99999)
PID=$(python3 -c 'import json;print(json.load(open("watcher_status.json"))["pid"])' 2>/dev/null)
if [ "$AGE" -le 180 ] && [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then echo "ok pid $PID heartbeat ${AGE}s"; exit 0; fi
# Safety rule: no name-based kills (pkill/killall). Stop ONLY the pid recorded in the pidfile
# (fallback: watcher_status.json pid), and only after its /proc cmdline is confirmed to be this desk's adaptive_watcher.py.
PIDFILE=adaptive_watcher.pid
DRY=${ENSURE_WATCHER_DRY_RUN:-0}
is_our_watcher(){ # $1=pid -> 0 if /proc/$1/cmdline runs adaptive_watcher.py from this desk/paper dir
  [ -n "$1" ] && [ -r "/proc/$1/cmdline" ] || return 1
  tr '\0' ' ' < "/proc/$1/cmdline" | grep -Eq '(^| )python3?[^ ]* +(\S*/)?adaptive_watcher\.py( |$)' || return 1
  [ "$(readlink "/proc/$1/cwd" 2>/dev/null)" = "$HERE" ]
}
OLD=""; [ -f "$PIDFILE" ] && OLD=$(tr -dc '0-9' < "$PIDFILE")
[ -z "$OLD" ] && OLD="$PID"
if [ -n "$OLD" ] && is_our_watcher "$OLD"; then
  if [ "$DRY" = 1 ]; then echo "DRY RUN: would kill verified watcher pid $OLD"; else kill "$OLD" 2>/dev/null; sleep 1; fi
elif [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
  echo "$(date '+%F %T') ensure_watcher: pid $OLD is alive but is NOT adaptive_watcher.py; left untouched" | tee -a watcher.log
fi
if [ "$DRY" = 1 ]; then echo "DRY RUN: would start adaptive_watcher.py and write $PIDFILE (heartbeat age ${AGE}s, old pid ${OLD:-none})"; exit 0; fi
nohup python3 adaptive_watcher.py >> watcher.log 2>&1 &
NEW=$!; echo "$NEW" > "$PIDFILE"
echo "$(date '+%F %T') ensure_watcher: restarted (heartbeat age ${AGE}s, old pid ${OLD:-none}) -> new pid $NEW" | tee -a watcher.log
