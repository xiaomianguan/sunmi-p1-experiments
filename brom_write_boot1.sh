#!/usr/bin/env bash
# brom_write_boot1.sh [--restore]
#
# Writes the eMMC boot1 area, which on this device holds the PRELOADER.
#
# Why boot1: the user area has no preloader partition in the GPT, and a read of
# the user area came back all zeros, while boot1 contains a complete preloader
# ("EMMC_BOOT" header, AND_ROMINFO_v, AND_SECCTRL_v, MTK_BLOADER_INFO_v21,
# preloader_rlk6580_we_c_m.bin) including MTK's seclib secure-boot library:
#     seclib_boot.c  [%s] Verification Pass / Fail(0x%x) / Verifying %s
#     [%s] invalid sboot config   [%s] Loading SEC config   [%s] is secro
# and AND_SECCTRL_v lists the images it verifies: lk, logo, boot, recovery,
# system, secro.
#
# This is the TEST payload: a single byte inside a plain log string
# ("mtk_arch_reset at pre-loader!" -> "...pre-loader?").  If the device still
# boots, BROM does not verify the preloader and we can patch the verification
# logic itself.  If it does not boot, the preloader is verified and that route
# is closed too.
#
# One BROM session does:
#   rf  the current boot1            <- captured FIRST, exact rollback
#   wf  our patched boot1
#   rf  boot1 again                  <- read back and compared
#   reset
set -u
cd "$(dirname "$0")" || exit 1

MODE="${1:-write}"
TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/write_boot1_${MODE#--}_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"
OUT="boot1_test"
VER="boot1_verify"
mkdir -p "$OUT" "$VER"

PAYLOAD="$OUT/preloader_boot1_test.img"

if [ "$MODE" = "--restore" ]; then
  # MUST use the untouched dump from 18:13 (before any boot1 write).
  # The first --restore attempt re-captured boot1 into boot1_before.bin and then
  # wrote that back, i.e. it "restored" the PATCHED preloader - which is why the
  # device still would not boot.  Never re-capture in restore mode.
  SRC="dumps/preloader_boot1.bin"
  [ -s "$SRC" ] || { echo "!! $SRC missing" >&2; exit 1; }
  echo "Restoring from the known-good dump: $SRC"
  echo "  md5: $(md5sum "$SRC" | cut -d' ' -f1)   (expect f0e674314f75f8417322aef35385c287)"
  TITLE="RESTORE the stock preloader (from the 18:13 dump)"
else
  [ -s "$PAYLOAD" ] || { echo "!! $PAYLOAD missing" >&2; exit 1; }
  SRC="$PAYLOAD"
  TITLE="TEST: patched preloader (1 byte in a log string)"
fi

echo "==============================================================="
echo " Sunmi P1 (MT6580) - $TITLE"
echo " Payload  : $SRC"
echo " Target   : eMMC boot1 (preloader), parttype=boot1, whole region"
echo " Log      : $LOG"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Pull the BATTERY, wait ~10s, reinsert."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in (catch BROM)."
echo

# NOTE: mtkclient parses each sub-command with the FULL parser
# (mtk_main.py: self.args = parser.parse_args(rcmd.split(" "))), so --parttype
# must be given *inside every command* - a top-level --parttype is ignored for
# the sub-commands and rf/wf then default to the user area (which is how we
# accidentally started reading all 7.8 GB).
if [ "$MODE" = "--restore" ]; then
  # no capture: write the known-good dump, then read back to verify
  CMDS="wf --parttype boot1 $SRC;"
  CMDS+="rf --parttype boot1 $VER/boot1_restored.bin;"
else
  CMDS="rf --parttype boot1 $VER/boot1_before.bin;"
  CMDS+="wf --parttype boot1 $SRC;"
  CMDS+="rf --parttype boot1 $VER/boot1_after.bin;"
fi
CMDS+="reset"

attempt=0
while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  cur=$(lsusb 2>/dev/null | grep -o '0e8d:[0-9a-fA-F]*' | head -1)
  echo
  echo "### attempt $attempt - waiting for BROM (0e8d:0003); currently: ${cur:-no device}"
  timeout 300 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee -a "$LOG"

  # guard: boot1 is 4 MB; if the read ballooned we fell back to the user area
  if [ -s "$VER/boot1_before.bin" ]; then
    sz=$(stat -c%s "$VER/boot1_before.bin")
    if [ "$sz" -gt 8388608 ]; then
      echo "!! boot1_before.bin is $sz bytes - parttype was ignored; aborting"
      exit 1
    fi
  fi

  if [ "$MODE" = "--restore" ]; then VFILE="$VER/boot1_restored.bin"; else VFILE="$VER/boot1_after.bin"; fi
  if [ -s "$VFILE" ] && cmp -s "$SRC" "$VFILE"; then
    echo
    echo "==============================================================="
    echo " VERIFY OK - boot1 written and read back identical."
    if [ "$MODE" = "--restore" ]; then
      echo " Original preloader restored."
    else
      echo " Now boot it. If it comes up, the preloader is patchable."
      echo " Rollback: ./brom_write_boot1.sh --restore"
    fi
    echo " Captured original: $VER/boot1_before.bin"
    echo "==============================================================="
    exit 0
  fi
  echo "### write not confirmed - retrying in 5s (attempt $attempt)"
  sleep 5
done

echo "!! gave up after $attempt attempts"
exit 1
