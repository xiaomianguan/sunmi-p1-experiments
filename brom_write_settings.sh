#!/usr/bin/env bash
# brom_write_settings.sh - write the two patched /data blocks that enable ADB.
#
# Only two 4 KB blocks of the userdata partition change:
#   /data/system/users/0/settings_global.xml
#     adb_enabled               0 -> 1     (brings up ADB)
#     install_non_market_apps   0 -> 1     (allows sideloaded APKs)
#
# The file size, its inode, its extents, the block bitmaps and the journal are all
# untouched - we are only overwriting existing data blocks in place. The filesystem
# was cleanly unmounted (s_state = EXT4_VALID_FS), so there is no journal replay
# that could undo this.
#
# Rollback: the original block contents are in dumps/userdata.bin.rollback/ - just
# run the same `wo` commands with those files instead.
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/write_settings_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"

B1=0xd2c42000
B2=0xd2c43000
F1=wowrites/wo_58442000.bin
F2=wowrites/wo_58443000.bin

[ -s "$F1" ] && [ -s "$F2" ] || { echo "!! missing $F1 / $F2" >&2; exit 1; }

echo "==============================================================="
echo " Sunmi P1 - write patched /data blocks (enable ADB)"
echo " Log: $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device off the USB bus."
echo
echo ">>> STEP 2: Pull the BATTERY, wait ~10s, reinsert (needed for a cold boot)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in."
echo

CMDS="wo $B1 0x1000 $F1;"
CMDS+="wo $B2 0x1000 $F2;"
CMDS+="ro $B1 0x2000 dumps/settings_verify.bin;"
CMDS+="reset"

# mtkclient gives up waiting for the device after ~10 minutes, so retry in a loop
# until the write is actually verified. That way the catcher never "times out" -
# you can plug in whenever, even hours later.
attempt=0
while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  rm -f dumps/settings_verify.bin
  echo
  echo "### attempt $attempt - waiting for BROM (plug in whenever ready)..."
  timeout 900 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee -a "$LOG"
  if [ -s dumps/settings_verify.bin ] && cmp -s <(cat "$F1" "$F2") dumps/settings_verify.bin; then
    echo
    echo "==============================================================="
    echo " VERIFY OK - both blocks written and read back identical."
    echo " Now unplug and power on. Android should start ADB."
    echo "==============================================================="
    exit 0
  fi
  echo "### write not confirmed - retrying in 5s (attempt $attempt)"
  sleep 5
done

echo "!! gave up after $attempt attempts"
