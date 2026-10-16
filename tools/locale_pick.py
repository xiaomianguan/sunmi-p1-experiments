#!/usr/bin/env python3
"""Scroll the Settings locale picker and tap the entry with the given label.

Android 6's LocalePicker applies the language as soon as you tap it, and it does
so as the *system* uid - so this changes persist.sys.locale properly, which the
shell itself is not allowed to do (SELinux denies shell setting persist.*).

The picker auto-scrolls to the current locale, and its labels are full locale
names ("English (United States)", not "English"), so we first scroll to the top
and then search downwards.

Usage: locale_pick.py ["English (United States)"]
"""
import re
import subprocess
import sys
import time

TARGET = sys.argv[1] if len(sys.argv) > 1 else "English (United States)"


def sh(*args):
    return subprocess.run(["adb", "shell", *args],
                          capture_output=True, text=True).stdout


def visible():
    sh("uiautomator", "dump", "/sdcard/ui.xml")
    xml = sh("cat", "/sdcard/ui.xml")
    out = []
    for m in re.finditer(r"<node[^>]*>", xml):
        n = m.group(0)
        t = re.search(r'text="([^"]*)"', n)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', n)
        if t and b and t.group(1):
            out.append((t.group(1), tuple(int(v) for v in b.groups())))
    return out


print("scrolling to the top...", flush=True)
for _ in range(6):
    sh("input", "swipe", "360", "400", "360", "1150", "150")
time.sleep(1)

for attempt in range(1, 13):
    items = visible()
    print(f"scroll {attempt}: {[t for t, _ in items][:6]}", flush=True)
    for text, (x1, y1, x2, y2) in items:
        if text == TARGET:
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            print(f"FOUND {TARGET!r} at ({cx},{cy}) - tapping", flush=True)
            sh("input", "tap", str(cx), str(cy))
            sys.exit(0)
    sh("input", "swipe", "360", "1000", "360", "400", "300")
    time.sleep(1)

print(f"!! {TARGET!r} not found", flush=True)
sys.exit(1)
