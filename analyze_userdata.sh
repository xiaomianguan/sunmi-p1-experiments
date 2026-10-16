#!/usr/bin/env bash
# analyze_userdata.sh
#   Wait for the userdata dump to complete, then locate and extract the /data
#   files we intend to edit. Read-only: it never modifies the image.
#
# The ext4 root IS /data, so device paths map like:
#   /data/system/users/0/settings_global.xml -> /system/users/0/settings_global.xml
set -u
cd "$(dirname "$0")" || exit 1

IMG=dumps/userdata.bin
WANT=5748621312          # 0x156780000 = full userdata partition size
OUT=analysis/userdata
mkdir -p "$OUT"

echo "[monitor] waiting for the dump to complete ($WANT bytes)..."
while true; do
  sz=$(stat -c %s "$IMG" 2>/dev/null || echo 0)
  [ "$sz" -ge "$WANT" ] && break
  sleep 30
done
echo "[monitor] dump complete: $(stat -c %s "$IMG") bytes"
sleep 5

echo "[monitor] filesystem sanity check"
debugfs -R 'stats' "$IMG" 2>/dev/null | grep -iE 'Filesystem features|Filesystem state|Block size|Inode size|Block count|Inode count' | tee "$OUT/fs_stats.txt"

echo "[monitor] listing directories"
{
  echo "=== / (fs root) ==="
  debugfs -R 'ls -l /' "$IMG" 2>&1
  echo
  echo "=== /system ==="
  debugfs -R 'ls -l /system' "$IMG" 2>&1
  echo
  echo "=== /system/users/0 ==="
  debugfs -R 'ls -l /system/users/0' "$IMG" 2>&1
  echo
  echo "=== /property ==="
  debugfs -R 'ls -l /property' "$IMG" 2>&1
} | tee "$OUT/dirlistings.txt"

echo "[monitor] extracting target files"
for f in \
  /system/users/0/settings_global.xml \
  /system/users/0/settings_system.xml \
  /system/users/0/settings_secure.xml \
  /system/packages.xml \
  /system/packages.list
do
  name=$(echo "$f" | tr '/' '_')
  echo "--- $f"
  debugfs -R "stat $f" "$IMG" 2>&1 | grep -E 'Inode|Size|EXTENTS|Type' | tee -a "$OUT/stat.txt"
  debugfs -R "dump $f $OUT$name" "$IMG" 2>&1 | tail -1
  [ -s "$OUT$name" ] && echo "    extracted $(stat -c %s "$OUT$name") bytes -> $OUT$name"
done

echo
echo "[monitor] extracted files:"
ls -la "$OUT"
echo "[monitor] DONE"
