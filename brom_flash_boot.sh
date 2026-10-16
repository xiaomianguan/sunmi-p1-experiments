#!/usr/bin/env bash
# brom_flash_boot.sh - write the Magisk-patched boot image, in ONE BROM session.
#
# Writes boot, reads it straight back for verification, then reboots.
# The stock boot image is preserved at dumps/boot.bin, so a rollback is:
#     ./venv/bin/python mtkclient/mtk.py w boot dumps/boot.bin
#
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_flash_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
IMG="magisk_patched_boot.img"
VERIFY="dumps/boot_verify.bin"

[ -s "$IMG" ] || { echo "!! $IMG missing - run ./host_patch.sh first" >&2; exit 1; }
[ -s dumps/boot.bin ] || { echo "!! dumps/boot.bin (stock) missing" >&2; exit 1; }

echo "==============================================================="
echo " Sunmi P1 (MT6580) - flash Magisk-patched boot image"
echo " Log: $LOG"
echo " Stock boot backup: dumps/boot.bin"
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

timeout 900 "$PY" "$MTK" multi "w boot $IMG;r boot $VERIFY;reset" 2>&1 | tee "$LOG"

echo
echo "==============================================================="
if [ -s "$VERIFY" ]; then
  if cmp -s "$VERIFY" "$IMG"; then
    echo " VERIFY OK - flash written and read back identical."
  else
    echo " !! VERIFY MISMATCH - re-flash before rebooting!"
    echo "    stock=$VERIFY  patched=$IMG"
  fi
fi
echo " Log: $LOG"
echo "==============================================================="
