#!/usr/bin/env bash
# Keep flywheel_watch.py (READ-ONLY) alive: single instance via flock; restart if the pid in flywheel_beat.json is gone
# or the beat is older than 300 s. Run it every 60 s from a loop (see README).
D="${FLYWHEEL_DIR:-$(cd "$(dirname "$0")" && pwd)}"
S="$(cd "$(dirname "$0")" && pwd)/flywheel_watch.py"
cd "$D" || exit 1
exec 9>"$D/.flywheel_supervise.lock"
flock -n 9 || { echo busy; exit 0; }
pid=$(python3 -c "import json;print(json.load(open('$D/flywheel_beat.json')).get('pid',''))" 2>/dev/null)
age=$(python3 -c "import json,time;print(int(time.time()-json.load(open('$D/flywheel_beat.json'))['wall']))" 2>/dev/null || echo 99999)
alive=0
if [ -n "$pid" ] && [ -r /proc/$pid/cmdline ] && tr '\0' ' ' < /proc/$pid/cmdline | grep -q "$S"; then alive=1; fi
if [ "$alive" = 1 ] && [ "$age" -lt 300 ]; then echo "ok pid $pid beat ${age}s"; exit 0; fi
for p in $(pgrep -f "python3 $S$"); do kill "$p" 2>/dev/null; done; sleep 2
setsid nohup python3 "$S" >>"$D/flywheel.log" 2>&1 < /dev/null 9>&- &
echo "$(date '+%F %T') ensure_flywheel_watch: restarted (alive=$alive beat_age=${age}s) -> new pid $!" | tee -a "$D/flywheel.log"
