#!/usr/bin/env bash
# do_restore.sh - emergency: restore the original seccfg and grab the preloader.
# Forced to BROM only (--pid 0x0003) so mtkclient never grabs the preloader port
# (which rejects our unsigned DA with DA_IMAGE_SIG_VERIFY_FAIL).
set -u
cd "$(dirname "$0")" || exit 1

LOG="logs/restore_$(date +%Y%m%d_%H%M%S).log"
PY="./venv/bin/python"

CMDS='w seccfg dumps/seccfg.bin;'
CMDS+='r seccfg dumps/seccfg_restored.bin;'
CMDS+='r preloader dumps/preloader_boot1.bin --parttype boot1;'
CMDS+='ro 0x0 0x100000 dumps/preloader_raw.bin;'
CMDS+='reset'

echo "### restoring seccfg from dumps/seccfg.bin (BROM only, pid 0x0003)"
echo "### log: $LOG"
"$PY" mtkclient/mtk.py --pid 0x0003 multi "$CMDS" 2>&1 | tee "$LOG"
echo "### done"
