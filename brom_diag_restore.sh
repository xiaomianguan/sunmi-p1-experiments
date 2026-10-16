#!/usr/bin/env bash
# brom_diag_restore.sh - gather boot-failure diagnostics, then restore the stock boot.
#
# One BROM session:
#   1. dump expdb     -> MTK's boot/exception log (may explain the failed boot)
#   2. dump seccfg    -> what LK wrote when it unlocked (lock state + imginfo table)
#   3. restore boot   -> stock boot image so the device boots again
#   4. verify + reset
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_diag_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"

echo "==============================================================="
echo " Sunmi P1 - diagnostics (expdb, seccfg) + restore stock boot"
echo " Log: $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device off the USB bus."
echo
echo ">>> STEP 2: Hold POWER 20-30s to force it off (it is boot-looping)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in."
echo

CMDS='r expdb dumps/expdb_after.bin;'
CMDS+='r seccfg dumps/seccfg_unlocked.bin;'
CMDS+='w boot dumps/boot.bin;'
CMDS+='r boot dumps/boot_verify.bin;'
CMDS+='reset'

timeout 1200 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee "$LOG"

echo
echo "==============================================================="
ls -la dumps/expdb_after.bin dumps/seccfg_unlocked.bin dumps/boot_verify.bin 2>/dev/null
if [ -s dumps/boot_verify.bin ] && cmp -s dumps/boot_verify.bin dumps/boot.bin; then
  echo " STOCK BOOT RESTORED and verified."
else
  echo " !! boot restore not verified - check the log"
fi
echo "==============================================================="
