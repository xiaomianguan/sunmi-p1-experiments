#!/usr/bin/env bash
# monitor_usb.sh - heartbeat + USB MODE DECODER for the BROM sessions.
#
# Appends a line every 5s to logs/read_live_monitor.log.  Watch it with:
#     tail -f logs/read_live_monitor.log
#
# The mode decode matters: 0e8d:0003 is the BootROM (what we need), while
# 0e8d:2000 / 0x2001 is the *preloader*, which mtkclient cannot talk to
# (handshake fails there).  0e8d:201d would mean adb is finally up.
set -u
cd "$(dirname "$0")" || exit 1
LOG="logs/read_live_monitor.log"
: > "$LOG"
last=""

while true; do
  ts=$(date '+%H:%M:%S')
  id=$(lsusb 2>/dev/null | grep -i '0e8d' | grep -o '0e8d:[0-9a-fA-F]*' | head -1)
  case "$id" in
    "")                  mode="no MediaTek device on USB (device off - good)" ;;
    0e8d:0003)           mode="*** BROM *** <- correct, catcher should grab it" ;;
    0e8d:2000|0e8d:2001) mode="!! PRELOADER (wrong mode) - battery pull + hold VOL UP" ;;
    0e8d:2008)           mode="MTP only (Android booted, no adb)" ;;
    0e8d:201d)           mode="*** MTP+ADB *** <- adb is up!" ;;
    *)                   mode="unknown id" ;;
  esac

  if ps -eo args --no-headers 2>/dev/null | grep -q 'mtkclient/mtk\.py'; then
    mtk="mtkclient RUNNING"
  else
    mtk="mtkclient idle"
  fi

  line="$ts  ${id:-none}  $mode  [$mtk]"
  if [ "$line" != "$last" ] || [ $(( $(date +%s) % 30 )) -lt 5 ]; then
    echo "$line" >> "$LOG"
    last="$line"
  fi
  sleep 5
done
