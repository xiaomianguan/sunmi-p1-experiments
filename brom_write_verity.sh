#!/usr/bin/env bash
# brom_write_verity.sh [--restore]
#
# Disables dm-verity ENFORCEMENT on /system by setting the persisted verity
# state to VERITY_MODE_LOGGING (1), which makes fs_mgr hand dm-verity the
# "ignore_corruption" behaviour.  A modified /system then mounts and reads
# normally, which is the gate for a custom ROM.
#
# Why this is the right lever (all verified against AOSP 6.0.1 and the device):
#   * /system is mounted from /dev/block/dm-0, fstab says "wait,verify".
#   * LK never sets androidboot.veritymode (no verity strings in lk.bin), and
#     "adb disable-verity" refuses: this is a user build, so the clean-disable
#     path (ALLOW_ADBD_DISABLE_VERITY) is not even compiled in.
#   * fs_mgr therefore reads the mode from a text TLV record in the 32 KB
#     dm-verity metadata block that sits between the filesystem and the
#     hashtree:
#         fs        0x00000000 .. 0x5F3DF000   (390111 x 4096, from the superblock)
#         metadata  0x5F3DF000 .. 0x5F3E7000   (hash_start_block 390119 x 4096)
#         hashtree  0x5F3E7000 .. 0x60000000
#     TLV area = metadata + 0x4000 ("skip cryptfs metadata area"), magic
#     0x01564c54, tags "verity_state_system" / "verity_lastsig_system".
#   * That block is NOT hashed by dm-verity, so rewriting it cannot break the
#     signed verity table.
#   * fs_mgr resets the state to DEFAULT if the lastsig tag does not match
#     SHA256(signature), so the payload pre-seeds both tags (see
#     tools/verity_disable_patch.py).
#
# One BROM session does:
#   ro  the current block           <- captured FIRST, so rollback is exact
#   wo  our patched block
#   ro  the block again             <- read back and compared
#   reset
set -u
cd "$(dirname "$0")" || exit 1

MODE="${1:-write}"
TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/write_verity_${MODE#--}_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
OUT="verity_disable"
VER="verity_verify"
mkdir -p "$VER"

# /system partition base 0x0A800000 (from dumps/gpt.bin) + fs offset 0x5F3E3000
ADDR="0x69be3000"
LEN="0x1000"
PAYLOAD="$OUT/blk_0x5F3E3000.bin"

if [ "$MODE" = "--restore" ]; then
  [ -s "$VER/orig_before.bin" ] || { echo "!! $VER/orig_before.bin missing (nothing captured yet)" >&2; exit 1; }
  SRC="$VER/orig_before.bin"
  TITLE="RESTORE the original dm-verity metadata block"
else
  [ -s "$PAYLOAD" ] || { echo "!! $PAYLOAD missing - run tools/verity_disable_patch.py first" >&2; exit 1; }
  SRC="$PAYLOAD"
  TITLE="DISABLE dm-verity enforcement on /system (mode = LOGGING)"
fi

echo "==============================================================="
echo " Sunmi P1 (MT6580) - $TITLE"
echo " Payload   : $SRC"
echo " Flash addr: $ADDR  ($LEN)   = system 0x0A800000 + 0x5F3E3000"
echo " Log       : $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Pull the BATTERY, wait ~10s, reinsert (cold boot)."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in (catch BROM 0e8d:0003)."
echo

CMDS="ro $ADDR $LEN $VER/orig_before.bin;"
CMDS+="wo $ADDR $LEN $SRC;"
rm -f "$VER/after.bin"
CMDS+="ro $ADDR $LEN $VER/after.bin;"
CMDS+="reset"

attempt=0
while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  cur=$(lsusb 2>/dev/null | grep -o '0e8d:[0-9a-fA-F]*' | head -1)
  echo
  echo "### attempt $attempt - waiting for BROM (0e8d:0003); currently: ${cur:-no device}"
  echo "###   short attempts on purpose: a catcher that grabbed the preloader gets replaced"
  timeout 180 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee -a "$LOG"

  if [ -s "$VER/after.bin" ] && cmp -s "$SRC" "$VER/after.bin"; then
    echo
    echo "==============================================================="
    echo " VERIFY OK - dm-verity metadata block written and read back identical."
    if [ "$MODE" = "--restore" ]; then
      echo " Original block restored."
    else
      echo " Next boot: fs_mgr should report 'Enabling dm-verity for system (mode 1)'"
      echo " and dm-verity will ignore corruption, so a modified /system boots."
      echo " Rollback: ./brom_write_verity.sh --restore"
    fi
    echo " Captured original: $VER/orig_before.bin"
    echo "==============================================================="
    exit 0
  fi
  echo "### write not confirmed - retrying in 5s (attempt $attempt)"
  sleep 5
done

echo "!! gave up after $attempt attempts"
exit 1
