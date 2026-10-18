#!/usr/bin/env bash
# Keep tg_watch.py (READ-ONLY public Telegram call watcher) alive. Single instance via flock; restarts if the pid in
# beat.json is gone or the beat is older than 180 s. State is on disk (state.json), so a restart resumes without
# re-alerting. Run every 60 s by start_tg_watch.sh.
D="${TGWATCH_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$D" || exit 1
exec 9>"$D/.supervise.lock"
flock -n 9 || { echo busy; exit 0; }
pid=$(python3 -c "import json;print(json.load(open('$D/beat.json')).get('pid',''))" 2>/dev/null)
age=$(python3 -c "import json,time;print(int(time.time()-json.load(open('$D/beat.json'))['wall']))" 2>/dev/null || echo 99999)
alive=0
if [ -n "$pid" ] && [ -r /proc/$pid/cmdline ] && tr '\0' ' ' < /proc/$pid/cmdline | grep -q "$D/tg_watch.py"; then alive=1; fi
if [ "$alive" = 1 ] && [ "$age" -lt 180 ]; then echo "ok pid $pid beat ${age}s"; exit 0; fi
for p in $(pgrep -f "python3 $D/tg_watch.py$"); do kill "$p" 2>/dev/null; done; sleep 2
setsid nohup python3 "$D/tg_watch.py" >>"$D/tg_watch.log" 2>&1 < /dev/null 9>&- &
echo "$(date '+%F %T') ensure_tg_watch: restarted (alive=$alive beat_age=${age}s old_pid=${pid:-none}) -> new pid $!" | tee -a "$D/tg_watch.log"
