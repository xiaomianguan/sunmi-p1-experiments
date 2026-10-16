#!/usr/bin/env bash
# brom_recon.sh - initial NON-DESTRUCTIVE mtkclient reconnaissance for the Sunmi P1 (MT6580).
#
# Usage:
#   1. Run this script FIRST (it waits for the device).
#   2. Power the P1 fully OFF.
#   3. Hold Volume Up (try Vol-Up, then both volume keys if that fails) and plug in USB.
#   4. Watch the output. Nothing is written to the device in this phase.
#
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_recon_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"

mkdir -p logs

echo "### Sunmi P1 BROM reconnaissance"
echo "### Log file : $LOG"
echo "### Waiting for an MTK BootROM device (USB 0e8d:0003)."
echo "### -> Power the device OFF, hold VOLUME UP, then plug in the USB cable."
echo

{
  echo "########## gettargetconfig ##########"
  timeout 700 "$PY" "$MTK" gettargetconfig
  echo "########## gettargetconfig exit: $? ##########"
  echo
  echo "########## printgpt ##########"
  timeout 700 "$PY" "$MTK" printgpt
  echo "########## printgpt exit: $? ##########"
} 2>&1 | tee "$LOG"

echo
echo "### Done. Full log saved to: $LOG"
