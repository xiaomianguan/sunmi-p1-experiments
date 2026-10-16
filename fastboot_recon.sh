#!/usr/bin/env bash
# fastboot_recon.sh - query the bootloader state over fastboot (read-only).
# Run this once the device is sitting in [Fastboot Mode] from the LK boot menu.
set -u
cd "$(dirname "$0")" || exit 1

TS=$(date +%Y%m%d_%H%M%S)
LOG="logs/fastboot_recon_${TS}.log"

{
  echo "########## fastboot devices ##########"
  timeout 20 fastboot devices -l
  echo
  echo "########## getvar all ##########"
  timeout 40 fastboot getvar all 2>&1
  echo
  echo "########## oem device-info ##########"
  timeout 20 fastboot oem device-info 2>&1
  echo
  echo "########## flashing get_unlock_ability ##########"
  timeout 20 fastboot flashing get_unlock_ability 2>&1
  echo
  echo "########## oem get_unlock_ability ##########"
  timeout 20 fastboot oem get_unlock_ability 2>&1
} 2>&1 | tee "$LOG"

echo
echo "### log: $LOG"
