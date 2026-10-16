#!/usr/bin/env bash
# fastboot_frp_probe.sh
#
# The MTK LK decides whether fastboot may unlock by reading an "unlock_allowed"
# flag out of the FRP partition (LK strings: "frp paritition addr/size" and
# "unlock_allowed_flag_offset"). The real record is keyed, but it is worth
# checking whether LK merely READS a plain value at a fixed offset -- if so we can
# just write it.
#
# Because `fastboot flash` works even on this locked bootloader, and
# `fastboot flashing get_unlock_ability` reads the result instantly, we can probe
# many candidates without a single reboot.
#
# The original FRP image is restored at the end (dumps/frp.bin).
set -u
cd "$(dirname "$0")" || exit 1

WORK=/tmp/frp_probe
ORIG=dumps/frp.bin
SIZE=$(stat -c %s "$ORIG")
mkdir -p "$WORK"

gen() { # gen <outfile> <python expression producing bytes(SIZE)>
  python3 -c "
import sys
SIZE=$SIZE
data=bytearray($2)
assert len(data)==SIZE, (len(data), SIZE)
open('$1','wb').write(bytes(data))
"
}

probe() {
  local name="$1" file="$2"
  printf '%-38s ' "$name"
  if ! timeout 30 fastboot flash frp "$file" >/dev/null 2>&1; then
    echo "flash FAILED"
    return
  fi
  local out
  out=$(timeout 15 fastboot flashing get_unlock_ability 2>&1 | grep -oE 'unlock_ability = [0-9]+')
  echo "${out:-<no response>}"
}

echo "FRP partition size: $SIZE bytes"
echo
echo "baseline (original FRP):"
probe "original" "$ORIG"
echo

# Candidate layouts. A "flag" is most likely a single byte/word somewhere.
gen "$WORK/all_ff.bin"      "bytearray([0xFF])*SIZE"
gen "$WORK/all_zero.bin"    "bytearray(SIZE)"
gen "$WORK/one_at_0.bin"    "bytearray(SIZE)[:0] + b'\\x01' + bytearray(SIZE-1)"
gen "$WORK/ones_all.bin"    "(b'\\x01'*SIZE)"
gen "$WORK/one_0x1000.bin"  "bytearray(0x1000) + b'\\x01' + bytearray(SIZE-0x1001)"
gen "$WORK/one_0x100.bin"   "bytearray(0x100) + b'\\x01' + bytearray(SIZE-0x101)"
gen "$WORK/one_end.bin"     "bytearray(SIZE-1) + b'\\x01'"
gen "$WORK/one_0x80000.bin" "bytearray(0x80000) + b'\\x01' + bytearray(SIZE-0x80001)"

probe "all 0xFF"          "$WORK/all_ff.bin"
probe "all 0x00 (blank)"  "$WORK/all_zero.bin"
probe "0x01 at offset 0"  "$WORK/one_at_0.bin"
probe "0x01 everywhere"   "$WORK/ones_all.bin"
probe "0x01 at 0x100"     "$WORK/one_0x100.bin"
probe "0x01 at 0x1000"    "$WORK/one_0x1000.bin"
probe "0x01 at 0x80000"   "$WORK/one_0x80000.bin"
probe "0x01 at last byte" "$WORK/one_end.bin"
echo

echo "restoring original FRP..."
timeout 30 fastboot flash frp "$ORIG" 2>&1 | grep -E 'OKAY|FAILED|Finished'
probe "restored original" "$ORIG"
