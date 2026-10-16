#!/usr/bin/env bash
# analyze_system.sh - inspect the dumped system.img with debugfs (NO sudo, no mount).
#
# Produces an inventory of every installed APK plus the interesting config files,
# so we can find exactly what enforces Sunmi's lockdown:
#   - the "unauthorized app installation is prohibited" whitelist
#   - the hidden developer options
#   - the locked system locale
set -u
cd "$(dirname "$0")" || exit 1

IMG=dumps/system.bin
OUT=analysis
mkdir -p "$OUT"

if [ ! -s "$IMG" ]; then
  echo "!! $IMG is missing or empty" >&2
  exit 1
fi

dbg() { debugfs -R "$1" "$IMG" 2>/dev/null; }

echo "### system.img size: $(stat -c %s "$IMG") bytes"

echo "### /system/app"     | tee "$OUT/app_list.txt"
dbg "ls -l /app"           | tee -a "$OUT/app_list.txt"
echo "### /system/priv-app" | tee -a "$OUT/app_list.txt"
dbg "ls -l /priv-app"      | tee -a "$OUT/app_list.txt"
echo "### /system/framework" | tee -a "$OUT/app_list.txt"
dbg "ls -l /framework"     | tee -a "$OUT/app_list.txt"

echo "### extracting build.prop"
dbg "dump /build.prop $OUT/build.prop"
ls -la "$OUT/build.prop" 2>/dev/null

echo "### extracting default locale / language configs"
for f in /etc/permissions/platform.xml; do
  dbg "dump $f $OUT/$(basename "$f")"
done

echo
echo "### APKs whose name mentions sunmi/sheng/pos/pay/mdm/security/guard"
dbg "ls -l /app"     | grep -iE 'sunmi|sheng|pos|pay|mdm|security|guard|lock' || true
dbg "ls -l /priv-app" | grep -iE 'sunmi|sheng|pos|pay|mdm|security|guard|lock' || true

echo
echo "### Done. See $OUT/"
ls -la "$OUT/"
