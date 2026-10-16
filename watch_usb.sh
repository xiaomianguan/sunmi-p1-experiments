#!/usr/bin/env bash
# watch_usb.sh - poll the USB bus and report every change of the Sunmi/MediaTek
# device state (MTP -> preloader -> BROM -> fastboot ...).
# No sudo required. Ctrl-C to stop.
prev="__init__"
while true; do
  cur=$(lsusb 2>/dev/null | grep -Ei '0e8d|mediatek|sunmi|google|android|linux foundation' | sort)
  if [ "$cur" != "$prev" ]; then
    echo "=== $(date +%H:%M:%S) ==="
    if [ -z "$cur" ]; then echo "  <no MediaTek/Android device on the bus>"; else echo "$cur" | sed 's/^/  /'; fi
    # decode the interesting PID for MTK
    if echo "$cur" | grep -q '0e8d:0003'; then echo "  >> MTK BOOTROM (BROM) MODE  <-- this is what we want"; fi
    if echo "$cur" | grep -q '0e8d:2000'; then echo "  >> MTK PRELOADER MODE"; fi
    if echo "$cur" | grep -q '0e8d:2008'; then echo "  >> MTK MTP (normal Android booted)"; fi
    prev="$cur"
  fi
  sleep 0.5
done
