#!/usr/bin/env bash
# brom_write.sh <partition> <file> [verify]
# Write a partition from a file in ONE BROM session, then optionally read it back.
#
# Examples:
#   ./brom_write.sh seccfg dumps/seccfg.bin          # restore original (locked) seccfg
#   ./brom_write.sh boot magisk_patched_boot.img     # flash patched boot
set -u
cd "$(dirname "$0")" || exit 1

PART="${1:?usage: brom_write.sh <partition> <file>}"
FILE="${2:?usage: brom_write.sh <partition> <file>}"
DO_VERIFY="${3:-}"

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_write_${PART}_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
VERIFY="dumps/${PART}_verify.bin"

[ -s "$FILE" ] || { echo "!! $FILE does not exist" >&2; exit 1; }

echo "==============================================================="
echo " Sunmi P1 (MT6580) - write partition '$PART'"
echo " Source : $FILE"
echo " Log    : $LOG"
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

CMDS="w $PART $FILE"
if [ -n "$DO_VERIFY" ]; then
  CMDS="$CMDS;r $PART $VERIFY"
fi
CMDS="$CMDS;reset"

# --pid 0x0003 forces BootROM only. Without it mtkclient happily connects to the
# preloader port, which rejects our unsigned DA with DA_IMAGE_SIG_VERIFY_FAIL.
timeout 900 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee "$LOG"

echo
echo "==============================================================="
if [ -n "$DO_VERIFY" ] && [ -s "$VERIFY" ]; then
  if cmp -s "$VERIFY" "$FILE"; then
    echo " VERIFY OK - '$PART' written and read back identical."
  else
    echo " !! VERIFY MISMATCH for '$PART'"
  fi
fi
echo " Log: $LOG"
echo "==============================================================="
