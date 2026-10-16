#!/usr/bin/env bash
# brom_unlock_try2.sh - attempt the unlock by editing ONLY the plaintext lock flag.
#
# Rationale: in the V3 seccfg the field at 0x20 (mtkclient's `seccfg_enc_len`) is in
# the PLAINTEXT header, i.e. outside the SEJ-encrypted blob. mtkclient's own source
# annotates it "0x1 = Locked, 0xF207 = Unlocked" and it writes 0x07F20000 to unlock.
# We flip exactly those two bytes and leave the encrypted blob untouched, so the
# (hardware-keyed) ciphertext stays valid. This tests whether LK consults that field.
#
# Also (re)writes the Magisk-patched boot so that if the flag IS honoured, the device
# comes up rooted in a single power cycle.
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/brom_unlock2_${TS}.log"
PY="./venv/bin/python"
MTK="mtkclient/mtk.py"

[ -s dumps/seccfg_unlock_plain.bin ] || { echo "!! run the seccfg edit first" >&2; exit 1; }
[ -s magisk_patched_boot.img ] || { echo "!! magisk_patched_boot.img missing" >&2; exit 1; }

echo "==============================================================="
echo " Sunmi P1 - unlock attempt 2: plaintext lock flag + Magisk boot"
echo " Log: $LOG"
echo " Rollback files: dumps/seccfg.bin  dumps/boot.bin"
echo "==============================================================="
echo
echo ">>> STEP 1: UNPLUG the USB cable from the P1 NOW."
while lsusb 2>/dev/null | grep -qi '0e8d'; do sleep 1; done
echo "    OK - device is off the USB bus."
echo
echo ">>> STEP 2: Force the P1 OFF - hold POWER for 20-30 seconds."
echo ">>> STEP 3: Hold VOLUME UP and plug the USB cable back in."
echo

CMDS='w seccfg dumps/seccfg_unlock_plain.bin;'
CMDS+='r seccfg dumps/seccfg_after_plain.bin;'
CMDS+='w boot magisk_patched_boot.img;'
CMDS+='reset'

# --pid 0x0003 forces BROM only. Essential here: the device is boot-looping, so it
# also exposes the preloader port (0e8d:2000/2001) which rejects our unsigned DA
# with DA_IMAGE_SIG_VERIFY_FAIL.
timeout 900 "$PY" "$MTK" --pid 0x0003 multi "$CMDS" 2>&1 | tee "$LOG"

echo
echo "==============================================================="
if [ -s dumps/seccfg_after_plain.bin ] && cmp -s dumps/seccfg_after_plain.bin dumps/seccfg_unlock_plain.bin; then
  echo " seccfg with the flipped flag is written and verified."
else
  echo " !! seccfg write could not be verified"
fi
echo " Now unplug, hold POWER 20-30s, and power on with NO cable attached."
echo "==============================================================="
