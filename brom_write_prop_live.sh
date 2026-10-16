#!/usr/bin/env bash
# brom_write_prop_live.sh [--restore]
#
# Writes the three /data blocks that create the persistent property
#   persist.sys.usb.config = mtp,adb
# which is the only lever for adb on this ROM (UsbDeviceManager derives
# mAdbEnabled from it, then sets adb_enabled itself).
#
# IMPORTANT: these payloads are built from LIVE reads (wowrites_live/), not from
# the offline snapshot.  The device re-initialised /data after our 20:38 dump, so
# the property files sit at different inode numbers and different data blocks now.
#
# One BROM session does:
#   ro  the victim's data block      <- captured FIRST so rollback is exact
#   wo  dir block / inode table / victim data block
#   ro  all three                    <- read back and compared
#   reset
set -u
cd "$(dirname "$0")" || exit 1

MODE="${1:-write}"
TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/write_prop_live_${MODE#--}_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
OUT="${OUTDIR:-wowrites_live}"
VER="${VERDIR:-prop_verify_live}"
mkdir -p "$VER"

[ -s "$OUT/victim.txt" ] || { echo "!! $OUT/victim.txt missing" >&2; exit 1; }
DIR_BLK=655872
ITB_BLK=655362
VICTIM_BLK=$(cut -d' ' -f1 "$OUT/victim.txt")
VICTIM_ADDR=$(cut -d' ' -f2 "$OUT/victim.txt")

if [ "$MODE" = "--restore" ]; then
  SRC="$OUT/orig"
  TITLE="RESTORE the original /data blocks"
else
  SRC="$OUT"
  TITLE="WRITE persist.sys.usb.config=mtp,adb (payloads built from live reads)"
fi

BLKS="$DIR_BLK $ITB_BLK $VICTIM_BLK"

echo "==============================================================="
echo " Sunmi P1 - $TITLE"
echo " Payloads: $SRC/"
echo " Victim  : $(cut -d' ' -f3-4 "$OUT/victim.txt")  block $VICTIM_BLK"
echo " Log     : $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Pull the BATTERY, wait ~10s, reinsert (needed for a cold boot)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in (catch BROM 0e8d:0003)."
echo

CMDS="ro $VICTIM_ADDR 0x1000 $VER/victim_before.bin;"
for blk in $BLKS; do
  b=$(printf 'wo_%012x.bin' "$blk")
  f="$SRC/$b"
  [ -s "$f" ] || { echo "!! missing payload $f" >&2; exit 1; }
  off=$(( 0x7A800000 + blk * 4096 ))
  rm -f "$VER/$b"
  CMDS+="wo 0x$(printf '%x' "$off") 0x1000 $f;"
  CMDS+="ro 0x$(printf '%x' "$off") 0x1000 $VER/$b;"
done
CMDS+="reset"

attempt=0
while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  cur=$(lsusb 2>/dev/null | grep -o '0e8d:[0-9a-fA-F]*' | head -1)
  echo
  echo "### attempt $attempt - waiting for BROM (0e8d:0003); currently: ${cur:-no device}"
  echo "###   short attempts on purpose: a catcher that grabbed the preloader gets replaced"
  timeout 180 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee -a "$LOG"

  ok=1
  for blk in $BLKS; do
    b=$(printf 'wo_%012x.bin' "$blk")
    [ -s "$VER/$b" ] || ok=0
    cmp -s "$SRC/$b" "$VER/$b" || ok=0
  done
  if [ "$ok" = 1 ]; then
    # keep the captured original of the victim's data block as a rollback payload
    [ -s "$VER/victim_before.bin" ] && \
      cp -f "$VER/victim_before.bin" "$OUT/orig/$(printf 'wo_%012x.bin' "$VICTIM_BLK")"
    echo
    echo "==============================================================="
    echo " VERIFY OK - all 3 blocks written and read back identical."
    if [ "$MODE" = "--restore" ]; then
      echo " /data blocks restored."
    else
      echo " Boot it: adb should come up as 0e8d:201d, and the framework"
      echo " will set adb_enabled=1 by itself."
    fi
    echo " Rollback: ./brom_write_prop_live.sh --restore"
    echo "==============================================================="
    exit 0
  fi
  echo "### write not confirmed - retrying in 5s (attempt $attempt)"
  sleep 5
done

echo "!! gave up after $attempt attempts"
exit 1
