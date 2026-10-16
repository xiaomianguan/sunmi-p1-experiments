#!/usr/bin/env bash
# brom_unlock.sh - unlock the Sunmi P1 bootloader by rewriting seccfg, in ONE BROM session.
#
# What this does:
#   da seccfg unlock  -> reads the V3 seccfg, sets seccfg_enc_len=0x07F20000 and
#                        seccfg_attr=ATTR_UNLOCK, re-encrypts the hash via the SEJ
#                        hardware emulation, and writes the partition back.
#   reset             -> reboot the device
#
# SAFETY: dumps/seccfg.bin holds the ORIGINAL locked seccfg. If the device stops
# booting after this, restore it with:
#     ./venv/bin/python mtkclient/mtk.py w seccfg dumps/seccfg.bin
#
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_unlock_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"

mkdir -p logs

if [ ! -s dumps/seccfg.bin ]; then
  echo "!! dumps/seccfg.bin missing - take the backup first (brom_dump.sh)" >&2
  exit 1
fi

echo "==============================================================="
echo " Sunmi P1 (MT6580) - BOOTLOADER UNLOCK (seccfg)"
echo " Log: $LOG"
echo " Original seccfg backed up at: dumps/seccfg.bin"
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
echo "    (mtkclient is waiting for the BootROM handshake)"
echo

timeout 900 "$PY" "$MTK" multi 'da seccfg unlock;reset' 2>&1 | tee "$LOG"

echo
echo "==============================================================="
echo " Done. Log: $LOG"
echo
echo " The device should now reboot. If it does not boot at all, restore"
echo " the original seccfg with:"
echo "   ./venv/bin/python mtkclient/mtk.py w seccfg dumps/seccfg.bin"
echo "==============================================================="
