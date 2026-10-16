#!/usr/bin/env bash
# brom_read_back.sh - read back what we wrote, to find out whether the
# persist.sys.usb.config patch survived the boot.
#
#   sb    0x7a800000   superblock            (mount count, state, kbytes written)
#   dir   0x11aa00000  /property dir block   (is our dirent still there?)
#   itblk 0x11a802000  group-20 inode table  (is i_size still 7 / links 2?)
#   data  0x11ba05000  victim data block     (is it still "mtp,adb"?)
#
# READ ONLY, no reset (so the device does not boot Android and write more).
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/read_back_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
OUT="live2"
mkdir -p "$OUT"

BLOCKS="
sb:0x7a800000
jrnl:0x1caa00000
dir:0x11aa00000
itblk:0x11a802000
data:0x11c204000
"

echo "==============================================================="
echo " Sunmi P1 - READ BACK the patched /data blocks (READ ONLY)"
echo " Log: $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Pull the BATTERY, wait ~10s, reinsert (needed for a cold boot)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in (catch BROM 0e8d:0003)."
echo ">>> When this finishes, UNPLUG and pull the battery - do NOT let it boot."
echo

CMDS=""
for spec in $BLOCKS; do
  name="${spec%%:*}"; off="${spec##*:}"
  rm -f "$OUT/${name}.bin"
  CMDS+="ro $off 0x1000 $OUT/${name}.bin;"
done

attempt=0
while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  cur=$(lsusb 2>/dev/null | grep -o '0e8d:[0-9a-fA-F]*' | head -1)
  echo
  echo "### attempt $attempt - waiting for BROM (0e8d:0003); currently: ${cur:-no device}"
  timeout 180 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee -a "$LOG"
  ok=1
  for spec in $BLOCKS; do
    name="${spec%%:*}"
    [ -s "$OUT/${name}.bin" ] || ok=0
  done
  if [ "$ok" = 1 ]; then
    echo
    echo "==============================================================="
    echo " READ OK - blocks saved in $OUT/"
    echo " Now UNPLUG and pull the battery.  Do NOT boot Android."
    echo "==============================================================="
    exit 0
  fi
  echo "### read incomplete - retrying in 5s (attempt $attempt)"
  sleep 5
done
echo "!! gave up after $attempt attempts"
exit 1
