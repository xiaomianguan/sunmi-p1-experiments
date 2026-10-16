#!/usr/bin/env bash
# brom_dump_userdata.sh - full userdata dump over BROM (BROM-only catcher).
#
# WHY: /system is dm-verity protected, but /data is not. The settings that gate
# developer options / ADB / locale / the woyou.market install gatekeeper all live
# in /data/system/... so that is where we need to write.
#
# To edit those files we need the ext4 layout, which needs the whole filesystem,
# so we take a complete dump first (it doubles as a /data backup).
#
# Read speed over the legacy DA is ~2 MB/s, so 5.35 GB takes roughly 45 minutes.
# The session is unattended - just keep the device plugged in.
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/dump_userdata_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
OUT="dumps/userdata.bin"

echo "==============================================================="
echo " Sunmi P1 - FULL userdata dump"
echo " Log : $LOG"
echo " Out : $OUT  (~5.35 GiB, ~45 min at ~2 MB/s)"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device off the USB bus."
echo
echo ">>> STEP 2: SHUT DOWN ANDROID PROPERLY if it is running (hold Power ->"
echo "           Power off). A clean unmount keeps the ext4 journal clean, which"
echo "           matters when we edit files in place later."
echo ">>> STEP 3: Pull the BATTERY, wait ~10s, reinsert it (the power button does"
echo "           not cold-boot this device, and BootROM only appears on a cold boot)."
echo ">>> STEP 4: Hold VOLUME UP and plug the USB cable back in."
echo

timeout 5400 "$PY" "$MTK" --pid 0x0003 r userdata "$OUT" 2>&1 | tee "$LOG"

echo
echo "==============================================================="
ls -la "$OUT" 2>/dev/null
echo " Done. Log: $LOG"
echo "==============================================================="
