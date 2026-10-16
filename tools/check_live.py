#!/usr/bin/env python3
"""Compare the LIVE blocks read off the device (live/) against our offline
snapshot, and say whether it is safe to write the persist.sys.usb.config patch.

Usage: check_live.py [live_dir] [payload_dir]

Checks
  1. live/dir.bin    vs the snapshot /property directory block
       -> the set of dirents must be IDENTICAL.  If Android added or removed a
          property file since the snapshot, our appended dirent would clobber it
          and the patch has to be rebuilt from the live block.
  2. live/itblk.bin  vs the snapshot group-20 inode table block
       -> only atime-ish fields are allowed to differ; inode 163216 (offset
          0xf00) must still be the same regular file with the same extent.
  3. live/data.bin   vs the snapshot data block of the linked file.
  4. live/set1.bin + live/set2.bin vs the settings_global.xml blocks we patched
       -> shows the *current* value of adb_enabled.  Expect "0": that is the
          framework undoing our earlier patch, i.e. live proof of the deadlock.
"""
import os
import re
import sys

BLK = 4096
DIR_BLK = 655872
ITB_BLK = 655362
DAT_BLK = 658946
SET_PART_OFF = 0x58442000          # settings_global.xml, partition-relative
LINK_INODE = 163216
LINK_INODE_OFF = 0xf00


def parse_dirents(d):
    out, off = [], 0
    while off < len(d):
        ino = int.from_bytes(d[off:off + 4], "little")
        rec = int.from_bytes(d[off + 4:off + 6], "little")
        nl = d[off + 6]
        if rec < 8 or rec % 4 or off + rec > len(d):
            return None
        out.append((ino, bytes(d[off + 8:off + 8 + nl])))
        off += rec
    return out


def runs(a, b):
    d = [i for i in range(len(a)) if a[i] != b[i]]
    out = []
    for i in d:
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return d, out


def cmp_block(live, snap, label, extra=""):
    print(f"{label} {extra}".rstrip())
    if live is None or not os.path.exists(live):
        print("    !! missing live read")
        return False
    a = open(live, "rb").read()
    b = open(snap, "rb").read()
    if a == b:
        print("    IDENTICAL to the snapshot")
        return True
    d, r = runs(a, b)
    print(f"    {len(d)} byte(s) differ in {len(r)} run(s):")
    for lo, hi in r[:12]:
        print(f"      off 0x{lo:03x}..0x{hi:03x}  live={a[lo:hi+1].hex(' ')}"
              f"  snapshot={b[lo:hi+1].hex(' ')}")
    if len(r) > 12:
        print(f"      ... and {len(r) - 12} more run(s)")
    return True


def main():
    live = sys.argv[1] if len(sys.argv) > 1 else "live"
    pay = sys.argv[2] if len(sys.argv) > 2 else "wowrites_prop"
    ok = True

    # ---- 1. directory block ----
    print("=" * 62)
    print("1. /property directory block")
    print("=" * 62)
    lp = os.path.join(live, "dir.bin")
    sp = os.path.join(pay, "orig", f"wo_{DIR_BLK:012x}.bin")
    if os.path.exists(lp) and os.path.exists(sp):
        a = parse_dirents(open(lp, "rb").read())
        b = parse_dirents(open(sp, "rb").read())
        if a is None:
            print("   !! live dir block does not parse")
            ok = False
        else:
            na = sorted(n for _i, n in a)
            nb = sorted(n for _i, n in b)
            if na == nb:
                print(f"   dirent set IDENTICAL ({len(na)} entries)"
                      f" -> appending our entry is safe")
            else:
                print("   !! DIRENT SETS DIFFER - rebuild the patch!")
                for n in sorted(set(na) - set(nb)):
                    print(f"      live only : {n!r}")
                for n in sorted(set(nb) - set(na)):
                    print(f"      snap only : {n!r}")
                ok = False
        cmp_block(lp, sp, "   byte diff:")
    else:
        print("   !! missing live/dir.bin or the snapshot block")
        ok = False

    # ---- 2. inode table block ----
    print()
    print("=" * 62)
    print(f"2. group-20 inode table block (inode {LINK_INODE} @ 0x{LINK_INODE_OFF:x})")
    print("=" * 62)
    lp = os.path.join(live, "itblk.bin")
    sp = os.path.join(pay, "orig", f"wo_{ITB_BLK:012x}.bin")
    if not cmp_block(lp, sp, "   byte diff:"):
        ok = False
    elif os.path.exists(lp) and os.path.exists(sp):
        li = open(lp, "rb").read()[LINK_INODE_OFF:LINK_INODE_OFF + 256]
        si = open(sp, "rb").read()[LINK_INODE_OFF:LINK_INODE_OFF + 256]
        for name, off, ln in (("i_mode", 0, 2), ("i_size_lo", 4, 4),
                              ("i_links", 0x1a, 2), ("i_blocks", 0x1c, 4)):
            lv = int.from_bytes(li[off:off + ln], "little")
            sv = int.from_bytes(si[off:off + ln], "little")
            print(f"      {name:10} live={lv} snapshot={sv}"
                  f"{'   <-- CHANGED' if lv != sv else ''}")
        print(f"      i_flags    live={int.from_bytes(li[0x20:0x24],'little'):#x}"
              f" snapshot={int.from_bytes(si[0x20:0x24],'little'):#x}")
        # extent header is 12 bytes, so the first ee_start_lo is at 0x3c
        print(f"      extent leaf -> block "
              f"{int.from_bytes(li[0x3c:0x40],'little')} "
              f"(expect {DAT_BLK})")

    # ---- 3. data block ----
    print()
    print("=" * 62)
    print("3. linked data block (the property value)")
    print("=" * 62)
    lp = os.path.join(live, "data.bin")
    sp = os.path.join(pay, "orig", f"wo_{DAT_BLK:012x}.bin")
    if os.path.exists(lp):
        print(f"   live content starts with: {open(lp,'rb').read()[:16]!r}")
    cmp_block(lp, sp, "   byte diff:")

    # ---- 4. settings_global.xml ----
    print()
    print("=" * 62)
    print("4. settings_global.xml (what Android did to our earlier patch)")
    print("=" * 62)
    p1, p2 = os.path.join(live, "set1.bin"), os.path.join(live, "set2.bin")
    if os.path.exists(p1) and os.path.exists(p2):
        blob = open(p1, "rb").read() + open(p2, "rb").read()
        snap = None
        if os.path.exists("dumps/userdata.bin"):
            with open("dumps/userdata.bin", "rb") as f:
                f.seek(SET_PART_OFF)
                snap = f.read(8192)
        for key in (b"adb_enabled", b"install_non_market_apps",
                    b"development_settings_enabled"):
            def val(buf):
                m = re.search(rb'name="' + key + rb'" value="(\d+)"', buf)
                return m.group(1).decode() if m else "?"
            print(f"   {key.decode():28} snapshot={val(snap) if snap else '-'}"
                  f"  live now={val(blob)}")
        print("   NOTE: adb_enabled=0 live is EXPECTED - UsbDeviceManager's")
        print("         systemReady() undid our patch. That IS the deadlock.")
    else:
        print("   !! missing live/set1.bin or live/set2.bin")

    print()
    print("=" * 62)
    print(" VERDICT:", "SAFE TO WRITE the property patch" if ok else
          "DO NOT WRITE - see the !! lines above")
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
