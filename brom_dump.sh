#!/usr/bin/env bash
# brom_dump.sh - full single-session dump of the Sunmi P1 (MT6580) via BootROM.
#
# WHY SINGLE SESSION: the MT6580 BootROM only answers the plug-in handshake during
# a short window after USB enumeration. Running two mtkclient processes back to back
# fails, because the second one sees the already-enumerated BROM, assumes it is
# "connected", and then the handshake times out.
#
# The script therefore waits until the cable is physically unplugged, so that
# mtkclient is already running and waiting when the device is plugged back in.
#
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_dump_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"

mkdir -p logs dumps

echo "==============================================================="
echo " Sunmi P1 (MT6580) - BootROM full dump, single session"
echo " Log file: $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
echo "           (waiting until no MediaTek USB device is present...)"
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Force the P1 fully OFF - hold POWER for ~15 seconds."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in."
echo
echo "    (mtkclient is now waiting for the BootROM handshake - plug in whenever ready)"
echo

# Everything in ONE mtkclient session:
#   printgpt  -> dump + display the GPT
#   rl dumps  -> dump every partition from the GPT into dumps/
#   r preloader ... --parttype boot1/boot2 -> the preloader is outside the GPT
CMDS='printgpt;rl dumps;r preloader dumps/preloader_boot1.bin --parttype boot1;r preloader dumps/preloader_boot2.bin --parttype boot2'

timeout 1200 "$PY" "$MTK" multi "$CMDS" 2>&1 | tee "$LOG"

echo
echo "==============================================================="
echo " Done. Log: $LOG"
echo " Partition dumps in: dumps/"
echo "==============================================================="
