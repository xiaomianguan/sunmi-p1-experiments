#!/usr/bin/env bash
# build_adb_boot.sh - build a boot image that brings up ADB with a ROOT shell.
#
# Because the bootloader is now unlocked (secure: no), LK no longer verifies boot
# images, so we can modify the ramdisk freely.
#
# Three edits to the stock ramdisk:
#   1. default.prop:  ro.debuggable=1  -> adbd runs as root (adb shell = root shell)
#                     ro.adb.secure=0  -> no RSA "allow debugging?" prompt
#                     ro.secure=0
#                     persist.sys.usb.config=mtp,adb
#   2. init.mt6580.usb.rc: make the plain "mtp" USB config expose mtp,adb and
#      start adbd. Needed because the framework only adds "adb" to the gadget when
#      Settings.Global.ADB_ENABLED is set, and we cannot set that without a shell.
#   3. fstab.mt6580: drop ",verify" from /system so /system mounts WITHOUT dm-verity
#      and can be modified (build.prop etc.).
set -e
cd "$(dirname "$0")" || exit 1

W="$(pwd)"
WORK="$W/build_adb"
rm -rf "$WORK"
mkdir -p "$WORK"
cd "$WORK"

cp "$W/dumps/boot.bin" boot.img
cp "$W/magisk_tools/libmagiskboot.so" ./magiskboot
chmod +x magiskboot

echo "== unpack =="
./magiskboot unpack boot.img >/dev/null

echo "== extract ramdisk files =="
for f in default.prop init.mt6580.usb.rc fstab.mt6580; do
  ./magiskboot cpio ramdisk.cpio "extract $f $f" >/dev/null
done
ls -la default.prop init.mt6580.usb.rc fstab.mt6580

echo "== 1) default.prop =="
sed -i 's/^ro\.adb\.secure=1/ro.adb.secure=0/'        default.prop
sed -i 's/^ro\.secure=1/ro.secure=0/'                 default.prop
sed -i 's/^ro\.debuggable=0/ro.debuggable=1/'         default.prop
sed -i 's/^persist\.sys\.usb\.config=mtp$/persist.sys.usb.config=mtp,adb/' default.prop
grep -nE 'adb|debuggable|secure|usb' default.prop

echo "== 2) init.mt6580.usb.rc : mtp -> mtp,adb + start adbd =="
python3 - <<'PY'
import re
p = 'init.mt6580.usb.rc'
s = open(p).read()
old = """on property:sys.usb.config=mtp
    write /sys/class/android_usb/android0/enable 0
    write /sys/class/android_usb/android0/idVendor ${sys.usb.vid}
    write /sys/class/android_usb/android0/idProduct 2008
    write /sys/class/android_usb/android0/functions ${sys.usb.config}
    write /sys/class/android_usb/android0/enable 1
    setprop sys.usb.state ${sys.usb.config}
"""
new = """on property:sys.usb.config=mtp
    write /sys/class/android_usb/android0/enable 0
    write /sys/class/android_usb/android0/idVendor ${sys.usb.vid}
    write /sys/class/android_usb/android0/idProduct 201D
    write /sys/class/android_usb/android0/functions mtp,adb
    write /sys/class/android_usb/android0/enable 1
    start adbd
    setprop sys.usb.state ${sys.usb.config}
"""
assert old in s, "mtp handler not found verbatim"
open(p,'w').write(s.replace(old, new, 1))
print("mtp handler patched")
PY
grep -n -A9 'sys.usb.config=mtp$' init.mt6580.usb.rc

echo "== 3) fstab.mt6580 : drop ,verify on /system =="
sed -i 's|/system ext4 ro wait,verify|/system ext4 ro wait|' fstab.mt6580
grep 'by-name/system' fstab.mt6580

echo "== put files back =="
./magiskboot cpio ramdisk.cpio \
  "add 0644 default.prop default.prop" \
  "add 0750 init.mt6580.usb.rc init.mt6580.usb.rc" \
  "add 0640 fstab.mt6580 fstab.mt6580" >/dev/null

echo "== repack =="
./magiskboot repack boot.img >/dev/null
ls -la new-boot.img
cp new-boot.img "$W/boot_adb_root.img"
echo
echo "== built: $W/boot_adb_root.img =="
