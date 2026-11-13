#!/bin/sh
# Start/stop/restart tools/bridge.py in the background (PID in logs/bridge.pid).
# The radio powers itself off when panel keepalives stop, so `restart` keeps the
# gap as short as possible: the new bridge starts right after the old one exits.
#
#   tools/bridge.sh start|stop|restart|status
#
# Port roles on this machine (udev names are historical and swapped):
#   /dev/ttyUSB.panel -> wired to the RADIO main unit
#   /dev/ttyUSB.ts480 -> wired to the front PANEL
set -e
cd "$(dirname "$0")/.."
RADIO=${RADIO:-/dev/ttyUSB.panel}
PANEL=${PANEL:-/dev/ttyUSB.ts480}
PIDFILE=logs/bridge.pid
mkdir -p logs

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

stop() {
    if running; then
        pid=$(cat "$PIDFILE"); kill "$pid"
        while kill -0 "$pid" 2>/dev/null; do sleep 0.05; done
    fi
    rm -f "$PIDFILE"
}

start() {
    if running; then echo "already running (pid $(cat "$PIDFILE"))"; return; fi
    setsid nohup .venv/bin/python -u tools/bridge.py --radio "$RADIO" --panel "$PANEL" \
        --inject 8490 --tap 8491 --keepalive "$@" >> logs/console.txt 2>&1 &
    echo $! > "$PIDFILE"
    echo "started pid $!"
}

case "$1" in
    start) shift; start "$@" ;;
    stop) stop ;;
    restart) shift; stop; start "$@" ;;
    status) if running; then echo "running pid $(cat "$PIDFILE")"; else echo "stopped"; fi ;;
    *) echo "usage: $0 start|stop|restart|status"; exit 2 ;;
esac
