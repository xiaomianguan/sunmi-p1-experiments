#!/usr/bin/env bash
# host_patch.sh - run Magisk's official boot_patch.sh on this Linux host.
#
# The Magisk APK ships magiskboot/magiskinit/magisk32 as native libraries for
# every ABI. We use the x86_64 magiskboot as a HOST tool, but keep magiskinit and
# magisk32 as the armeabi-v7a builds, because those get embedded into the ramdisk
# and must run on the MT6580 (32-bit ARMv7).
#
# Usage: ./host_patch.sh <stock_boot.img> <output.img>
# NOTE: no `set -u` here on purpose. Magisk's boot_patch.sh does `unset SKIP32` /
# `unset SKIP64` and then relies on them expanding to empty strings, which is
# exactly how the official script is written for Android's `sh`.
set -e

WORKDIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$WORKDIR/magisk_tools"
APK="$WORKDIR/tools/Magisk-v27.0.apk"

STOCK="${1:?usage: host_patch.sh <stock_boot.img> <output.img>}"
OUTPUT="${2:?usage: host_patch.sh <stock_boot.img> <output.img>}"

# Resolve to absolute paths before we cd anywhere.
case "$STOCK"  in /*) ;; *) STOCK="$WORKDIR/$STOCK" ;; esac
case "$OUTPUT" in /*) ;; *) OUTPUT="$WORKDIR/$OUTPUT" ;; esac
[ -s "$STOCK" ] || { echo "!! $STOCK does not exist" >&2; exit 1; }

PATCHDIR="$WORKDIR/magisk_patch"
rm -rf "$PATCHDIR"
mkdir -p "$PATCHDIR"
cd "$PATCHDIR"

# magiskboot -> host x86_64 build (runs on this machine)
cp "$TOOLS/libmagiskboot.so" magiskboot
# magiskinit / magisk32 -> armeabi-v7a (must run on the MT6580)
cp "$TOOLS/libmagiskinit.so" magiskinit
cp "$TOOLS/libmagisk32.so"   magisk32
# stub apk is embedded into the ramdisk
unzip -o -j -q "$APK" 'assets/stub.apk' -d .
cp "$STOCK" boot.img
chmod 755 magiskboot magiskinit magisk32

# ---- shims normally provided by Android's util_functions.sh -------------
export SOURCEDMODE=1          # tells boot_patch.sh we already set everything up
# Non-BOOTMODE = "install from recovery" path. That is what we want here: it makes
# boot_patch.sh skip `magisk32 --preinit-device` (an ARM binary we cannot execute on
# x86) and simply omit PREINITDEVICE, so magiskinit auto-detects it on the device.
# ui_print() is ours (see below), so it does not depend on BOOTMODE.
export BOOTMODE=false
export PREINITDEVICE=""       # defined-but-empty: avoids `set -u` errors
export API=23                 # Android 6.0
export ABI=armeabi-v7a
export ABI32=armeabi-v7a
export IS64BIT=false
export ARCH=arm
export KEEPVERITY=false
export KEEPFORCEENCRYPT=false
export PATCHVBMETAFLAG=false
export RECOVERYMODE=false
export LEGACYSAR=false

ui_print() { echo "$1"; }
abort() { echo "ABORT: $1" >&2; exit 1; }
recovery_cleanup() { :; }
grep_prop() { return 0; }
getprop() { echo ""; }
grep_get_prop() { echo ""; }

# shellcheck disable=SC1091
. "$TOOLS/boot_patch.sh" boot.img

if [ ! -f new-boot.img ]; then
  echo "!! repack produced no new-boot.img" >&2
  exit 1
fi

cp new-boot.img "$OUTPUT"
echo
echo "== patched boot image written to: $OUTPUT"
ls -la "$OUTPUT"
