#!/usr/bin/env bash
# post_root.sh - run from the HOST, over ADB, once the device is rooted.
# Delivers the three user-facing goals:
#   1. third-party app installs
#   2. changeable system language
#   3. developer options (+ ADB)
#
# Usage: ./post_root.sh [locale]      e.g. ./post_root.sh de-DE
set -u
LOCALE="${1:-en-US}"

adb wait-for-device
adb root  >/dev/null 2>&1 || true
sleep 2
adb wait-for-device

sh_() { adb shell "$@"; }
su_() { adb shell "su -c '$*'"; }

echo "### 1. Developer options"
sh_ settings put global development_settings_enabled 1

echo "### 2. ADB over USB (persistent)"
sh_ settings put global adb_enabled 1
su_ setprop persist.sys.usb.config mtp,adb
su_ setprop persist.adb.tcp.port 5555

echo "### 3. Allow installing third-party apps"
sh_ settings put global install_non_market_apps 1
sh_ settings put secure install_non_market_apps 1

echo "### 4. System language -> $LOCALE"
LANG_PART="${LOCALE%%-*}"
CTRY_PART="${LOCALE##*-}"
su_ setprop persist.sys.locale "$LOCALE"
su_ setprop persist.sys.language "$LANG_PART"
su_ setprop persist.sys.country "$CTRY_PART"
su_ setprop ctl.restart zygote

echo "### 5. Show what is still blocking things"
echo "--- device admins ---"
sh_ dumpsys device_policy | grep -iE 'admin|Package' | head -20
echo "--- suspicious packages ---"
for p in com.sunmi.baseservice com.sunmi.remotecontrol.pro woyou.market \
         com.sunmi.usercenter com.sunmi.security com.sunmi.toolbox; do
  echo -n "$p: "; sh_ pm list packages | grep -q "$p" && echo present || echo absent
done

echo
echo "### Done. Reboot to apply:  adb reboot"
