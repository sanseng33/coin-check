#!/bin/bash
# [desk] ./scheduler.sh start|stop|status
cd "$(dirname "$0")"
pid() { [ -f logs/scheduler.lock ] && cat logs/scheduler.lock; }
running() { p=$(pid); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
case "$1" in
  start)  if running; then echo "running pid $(pid)"; exit 0; fi
          mkdir -p logs
          nohup setsid python3 scheduler.py >> logs/scheduler.log 2>&1 < /dev/null &
          sleep 1; running && echo "started pid $(pid)" || { echo "failed:"; tail -3 logs/scheduler.log; } ;;
  stop)   running && kill "$(pid)" && echo "stopped" || echo "not running" ;;
  status) running && echo "running pid $(pid)" || echo "not running"; tail -5 logs/scheduler.log 2>/dev/null ;;
  *) echo "usage: $0 start|stop|status" ;;
esac
