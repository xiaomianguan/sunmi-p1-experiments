#!/usr/bin/env bash
# monitor_read.sh - heartbeat for the BROM read/write sessions.
#
# Appends one line every 15s to logs/read_live_monitor.log so you can watch
# progress with:   tail -f logs/read_live_monitor.log
set -u
cd "$(dirname "$0")" || exit 1
LOG="logs/read_live_monitor.log"
: > "$LOG"

while true; do
  ts=$(date '+%H:%M:%S')
  dev=$(lsusb 2>/dev/null | grep -i '0e8d' | sed 's/^.*ID //' | tr -d '\n')
  [ -z "$dev" ] && dev="(no MediaTek device on USB)"

  if ps -eo args --no-headers 2>/dev/null | grep -q '^[^ ]*mtk\.py'; then
    mtk="mtkclient RUNNING"
  elif ps -eo args --no-headers 2>/dev/null | grep -q 'mtk\.py --pid'; then
    mtk="mtkclient RUNNING"
  else
    mtk="mtkclient idle"
  fi

  echo "$ts  device: $dev   $mtk" >> "$LOG"
  sleep 15
done
