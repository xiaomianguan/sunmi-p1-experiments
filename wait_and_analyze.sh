#!/usr/bin/env bash
# wait_and_analyze.sh
#   1. Wait for the dump to finish system.bin + cache.bin
#   2. Stop mtkclient BEFORE it starts the 5.4 GB userdata dump (we are not wiping
#      userdata in the first attempt, so it stays on the device and can be dumped later)
#   3. Run the system.img analysis
set -u
cd "$(dirname "$0")" || exit 1

SYSTEM_SIZE=1610612736     # 0x60000000
CACHE_SIZE=268435456       # 0x10000000

echo "[watcher] waiting for system.bin to complete ($SYSTEM_SIZE bytes)..."
while true; do
  sz=$(stat -c %s dumps/system.bin 2>/dev/null || echo 0)
  [ "$sz" -ge "$SYSTEM_SIZE" ] && break
  sleep 10
done
echo "[watcher] system.bin complete."

echo "[watcher] waiting for cache.bin to complete ($CACHE_SIZE bytes)..."
while true; do
  sz=$(stat -c %s dumps/cache.bin 2>/dev/null || echo 0)
  [ "$sz" -ge "$CACHE_SIZE" ] && break
  # if mtkclient already moved on to userdata, bail out early
  [ -f dumps/userdata.bin ] && break
  sleep 5
done
echo "[watcher] cache.bin complete - stopping the dump before userdata."

pkill -f '[m]tkclient/mtk.py' 2>/dev/null
pkill -f '[b]rom_dump.sh' 2>/dev/null
sleep 3
rm -f dumps/userdata.bin

echo "[watcher] running system.img analysis..."
./analyze_system.sh

echo "[watcher] ALL DONE"
