#!/usr/bin/env bash
# brom_read_live.sh - READ (never write) the three /data blocks we are about to
# patch, so we can prove our offline snapshot is still current before writing.
#
#   block 655872  /property directory block        flash 0x11aa00000
#   block 655362  group-20 inode table, block 0    flash 0x11a802000
#   block 658946  data block of the linked file    flash 0x11b602000
#
# There is deliberately NO `reset` here: if the device booted Android it would
# write to /data again and invalidate everything we just read. After this runs,
# unplug and pull the battery - the device must stay off until the write step.
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/read_live_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
OUT="live"
mkdir -p "$OUT"

# name:flash_address - the three /data blocks we are about to patch, plus the two
# settings_global.xml blocks so we can re-confirm the earlier adb_enabled /
# install_non_market_apps patch is still intact.
BLOCKS="
dir:0x11aa00000
itblk:0x11a802000
data:0x11b602000
set1:0xd2c42000
set2:0xd2c43000
"

echo "==============================================================="
echo " Sunmi P1 - READ live /data blocks (READ ONLY)"
echo " Log: $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Pull the BATTERY, wait ~10s, reinsert (needed for a cold boot)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in."
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
  echo
  cur=$(lsusb 2>/dev/null | grep -o '0e8d:[0-9a-fA-F]*' | head -1)
  echo "### attempt $attempt - waiting for BROM (0e8d:0003); currently: ${cur:-no device}"
  echo "###   short attempts on purpose: a catcher that grabbed the preloader gets replaced"
  timeout 180 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee -a "$LOG"
  ok=1
  for spec in $BLOCKS; do
    name="${spec%%:*}"
    [ -s "$OUT/${name}.bin" ] || ok=0
  done
  if [ "$ok" = 1 ]; then
    echo
    echo "==============================================================="
    echo " READ OK - live blocks saved in $OUT/"
    echo " Now UNPLUG and pull the battery.  Do NOT boot Android."
    echo "==============================================================="
    exit 0
  fi
  echo "### read incomplete - retrying in 5s (attempt $attempt)"
  sleep 5
done
echo "!! gave up after $attempt attempts"
exit 1
