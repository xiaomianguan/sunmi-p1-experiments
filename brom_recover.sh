#!/usr/bin/env bash
# brom_recover.sh - undo the failed seccfg unlock and grab the preloader we need.
#
# One BROM session:
#   1. read back the seccfg we (badly) wrote   -> dumps/seccfg_bricked.bin
#   2. read the real preloader                 -> dumps/preloader_boot1.bin / preloader_raw.bin
#   3. restore the ORIGINAL seccfg             -> from dumps/seccfg.bin   (raw write, no SEJ!)
#   4. read it back to prove the restore       -> dumps/seccfg_restored.bin
#   5. reset
#
# Note step 3 is a plain byte-for-byte write, so it does NOT touch the broken SEJ
# emulation that caused the problem in the first place.
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_recover_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"

mkdir -p logs dumps

if [ ! -s dumps/seccfg.bin ]; then
  echo "!! dumps/seccfg.bin missing - cannot restore!" >&2
  exit 1
fi

echo "==============================================================="
echo " Sunmi P1 (MT6580) - RECOVER: restore original seccfg + get preloader"
echo " Log: $LOG"
echo " Original seccfg: dumps/seccfg.bin ($(stat -c %s dumps/seccfg.bin) bytes)"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
echo "           (waiting until no MediaTek USB device is present...)"
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Force the P1 OFF - hold POWER for 20+ seconds (it will not"
echo "           give any feedback, that is normal for a bricked MTK device)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in."
echo

CMDS='r seccfg dumps/seccfg_bricked.bin;'
CMDS+='r preloader dumps/preloader_boot1.bin --parttype boot1;'
CMDS+='ro 0x0 0x100000 dumps/preloader_raw.bin;'
CMDS+='w seccfg dumps/seccfg.bin;'
CMDS+='r seccfg dumps/seccfg_restored.bin;'
CMDS+='reset'

timeout 900 "$PY" "$MTK" multi "$CMDS" 2>&1 | tee "$LOG"

echo
echo "==============================================================="
echo " Log: $LOG"
echo
if [ -s dumps/seccfg_restored.bin ] && cmp -s dumps/seccfg_restored.bin dumps/seccfg.bin; then
  echo " RESTORE VERIFIED - seccfg matches the original byte for byte."
  echo " Unplug the cable and power the device on; it should boot normally."
else
  echo " !! Could not verify the restore. Check the log above."
fi
echo "==============================================================="
