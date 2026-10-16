#!/usr/bin/env bash
# brom_write_prop.sh [--restore]
#
# Write the three patched /data blocks that create the persistent property
#   persist.sys.usb.config = mtp,adb
# which is the ONLY way to get adb on this ROM: UsbDeviceManager derives
# mAdbEnabled from that property at boot (services.odex: applyAdbFunction), and
# then writes Settings.Global.ADB_ENABLED itself.  With the stock value "mtp"
# the framework instead forces adb_enabled back to 0 - a deadlock.
#
# The patch allocates nothing, so no block bitmap / inode bitmap / group
# descriptor / superblock block is touched:
#   block 655872  flash 0x11aa00000  /property dir block - one dirent appended
#   block 655362  flash 0x11a802000  grp20 inode table  - i_size 1->7, links 1->2
#   block 658946  flash 0x11b602000  the linked data block - "mtp,adb"
#
# --restore writes the original block contents (wowrites_prop/orig/) back.
set -u
cd "$(dirname "$0")" || exit 1

MODE="${1:-write}"
TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/write_prop_${MODE}_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
OUT="wowrites_prop"
VER="prop_verify"
mkdir -p "$VER"

if [ "$MODE" = "--restore" ]; then
  SRC="$OUT/orig"
  TITLE="RESTORE original /data blocks"
else
  SRC="$OUT"
  TITLE="WRITE persist.sys.usb.config=mtp,adb into /data"
fi

BLKS="655872 655362 658946"
CMDS=""
for blk in $BLKS; do
  f="$SRC/$(printf 'wo_%012x.bin' "$blk")"
  [ -s "$f" ] || { echo "!! missing payload $f" >&2; exit 1; }
  off=$(( 0x7A800000 + blk * 4096 ))
  rm -f "$VER/$(basename "$f")"
  CMDS+="wo 0x$(printf '%x' "$off") 0x1000 $f;"
  CMDS+="ro 0x$(printf '%x' "$off") 0x1000 $VER/$(basename "$f");"
done
CMDS+="reset"

echo "==============================================================="
echo " Sunmi P1 - $TITLE"
echo " Payloads: $SRC/"
echo " Log     : $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Pull the BATTERY, wait ~10s, reinsert (needed for a cold boot)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in."
echo

attempt=0
while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  echo
  cur=$(lsusb 2>/dev/null | grep -o '0e8d:[0-9a-fA-F]*' | head -1)
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
    echo
    echo "==============================================================="
    echo " VERIFY OK - all 3 blocks written and read back identical."
    if [ "$MODE" = "--restore" ]; then
      echo " /data blocks restored to their original contents."
    else
      echo " Now let it boot: adb should come up (0e8d:201d) and the"
      echo " framework will set adb_enabled=1 by itself."
    fi
    echo "==============================================================="
    exit 0
  fi
  echo "### write not confirmed - retrying in 5s (attempt $attempt)"
  sleep 5
done

echo "!! gave up after $attempt attempts"
exit 1
