#!/usr/bin/env python3
"""Create a persistent-property file inside /data/property using ONLY in-place
content edits - no block/inode is ever allocated.

Why this way
------------
Android's property service loads every file in /data/property at boot, using the
file name as the property name.  We need `persist.sys.usb.config = mtp,adb` so
that UsbDeviceManager sees adb in `getDefaultFunctions()` and sets
`mAdbEnabled = true` (see services.odex: applyAdbFunction / systemReady), which is
the only way to get adb on this ROM.

Creating that file the normal way (debugfs `write`) allocates an inode, a data
block, a dirent AND updates the block bitmap, inode bitmap, group descriptors and
superblock free counts.  Our offline image is a snapshot taken while the device
was off, so those allocation counters are stale by the time we flash - replaying
them could hand out blocks that Android is already using.

So instead we add the name as a HARD LINK to an existing property file and give
that file our value.  The cost is that the linked property (`persist.sys.pq.shp.idx`
by default - a display-sharpness index read as an int) now reads "mtp,adb", i.e.
parses to 0.  Nothing else is lost, and no allocator state is touched:

    block 655872  /property dir block   - append one dirent (dir size unchanged)
    block 655362  grp20 inode table     - i_size 1 -> 7, i_links_count 1 -> 2
    block 658946  the linked data block - "mtp,adb"

Because the dirent is only appended into the slack of the existing last record, the
directory's own size/block count never change, so its inode is not touched either.

Usage:
  make_property_patch.py <image> <outdir> [--property=NAME] [--value=VALUE]
                         [--link=PATH-IN-IMAGE] [--apply]

  --apply   also write the patched blocks into <image> in place (for e2fsck
            validation); the original blocks are saved to <outdir>/orig/
"""
import os
import re
import subprocess
import sys

PART_OFFSET = 0x7A800000          # userdata partition offset in flash
BLK = 4096
FT_REG_FILE = 1


def debugfs_stat(image, path):
    out = subprocess.run(["debugfs", "-R", f"stat {path}", image],
                         capture_output=True, text=True).stdout
    if "Inode:" not in out:
        sys.exit(f"!! cannot stat {path} in {image}\n{out}")
    ino = int(re.search(r"Inode:\s*(\d+)", out).group(1))
    # files print "Size: N" on its own line, directories print it on the
    # "User: .. Group: .. Size: N" line.  "Size of extra inode fields" and the
    # trailing "Fragment: ... Size: 0" both come later, so the first hit wins.
    size = int(re.search(r"Size:\s*(\d+)", out).group(1))
    links = int(re.search(r"Links:\s*(\d+)", out).group(1))
    ext = re.search(r"^\s*\(0\):(\d+)", out, re.M)
    if not ext:
        sys.exit(f"!! {path} has no (0) extent - refusing")
    return {"inode": ino, "size": size, "links": links, "block": int(ext.group(1))}


def group_layout(image, group):
    """Return (block_bitmap, inode_bitmap, inode_table) for an ext4 group."""
    out = subprocess.run(["dumpe2fs", "-g", image],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split(":")
        if len(f) >= 7 and f[0].isdigit() and int(f[0]) == group:
            return int(f[4]), int(f[5]), int(f[6])
    sys.exit(f"!! group {group} not found in dumpe2fs -g output")


def read_block(f, blk):
    f.seek(blk * BLK)
    d = f.read(BLK)
    assert len(d) == BLK
    return bytearray(d)


def parse_dirents(blk_data):
    """Walk the ext4 directory record chain; return list of dicts."""
    out, off = [], 0
    while off < BLK:
        ino = int.from_bytes(blk_data[off:off + 4], "little")
        rec = int.from_bytes(blk_data[off + 4:off + 6], "little")
        nl = blk_data[off + 6]
        ft = blk_data[off + 7]
        if rec < 8 or rec % 4 or off + rec > BLK:
            sys.exit(f"!! corrupt dirent at 0x{off:x} (rec_len={rec})")
        out.append({"off": off, "inode": ino, "rec_len": rec,
                    "name_len": nl, "file_type": ft,
                    "name": bytes(blk_data[off + 8:off + 8 + nl])})
        off += rec
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    image, outdir = args[0], args[1]

    prop = "persist.sys.usb.config"
    value = "mtp,adb"
    link = "/property/persist.sys.pq.shp.idx"
    for a in sys.argv[1:]:
        if a.startswith("--property="):
            prop = a.split("=", 1)[1]
        elif a.startswith("--value="):
            value = a.split("=", 1)[1]
        elif a.startswith("--link="):
            link = a.split("=", 1)[1]

    os.makedirs(outdir, exist_ok=True)
    origdir = os.path.join(outdir, "orig")
    os.makedirs(origdir, exist_ok=True)

    d = debugfs_stat(image, "/property")
    t = debugfs_stat(image, link)
    print(f"image     : {image}")
    print(f"/property : inode {d['inode']}, dir block {d['block']}")
    print(f"link src  : {link} -> inode {t['inode']}, "
          f"size {t['size']}, links {t['links']}, data block {t['block']}")
    print(f"new name  : {prop} = {value!r}")
    print()

    # ---- where does the linked inode live? (all params read from the fs) ----
    sb = subprocess.run(["dumpe2fs", "-h", image],
                        capture_output=True, text=True).stdout
    inode_size = int(re.search(r"Inode size:\s*(\d+)", sb).group(1))
    inodes_per_group = int(re.search(r"Inodes per group:\s*(\d+)", sb).group(1))
    first_block = int(re.search(r"First block:\s*(\d+)", sb).group(1))

    grp = (t["inode"] - 1) // inodes_per_group
    idx = (t["inode"] - 1) % inodes_per_group
    _bb, _ib, itable = group_layout(image, grp)
    inode_off_in_table = idx * inode_size
    itable_block = itable + first_block + inode_off_in_table // BLK
    off_in_block = inode_off_in_table % BLK
    print(f"inode {t['inode']}: group {grp}, inode table block {itable_block}, "
          f"offset 0x{off_in_block:x}")

    # ---- read the three blocks ----
    with open(image, "rb") as f:
        dirblk = read_block(f, d["block"])
        itblk = read_block(f, itable_block)
        datblk = read_block(f, t["block"])
        origs = {"dir": read_block(f, d["block"]),
                 "inode": read_block(f, itable_block),
                 "data": read_block(f, t["block"])}

    # ---- patch 1: append the dirent into the slack of the last record ----
    dirents = parse_dirents(dirblk)
    if any(e["name"] == prop.encode() for e in dirents):
        sys.exit(f"!! {prop} already exists in the directory")
    last = dirents[-1]
    if last["off"] + last["rec_len"] != BLK:
        sys.exit("!! last dirent does not reach the end of the block")

    min_len = 8 + ((last["name_len"] + 3) & ~3)
    need = 8 + ((len(prop) + 3) & ~3)
    if last["rec_len"] - min_len < need:
        sys.exit(f"!! no room: {last['rec_len'] - min_len} spare, need {need}")

    new_off = last["off"] + min_len
    new_rec_len = BLK - new_off
    dirblk[last["off"] + 4:last["off"] + 6] = min_len.to_bytes(2, "little")
    rec = (t["inode"].to_bytes(4, "little")
           + new_rec_len.to_bytes(2, "little")
           + bytes([len(prop), FT_REG_FILE]) + prop.encode())
    dirblk[new_off:new_off + len(rec)] = rec
    print(f"  dir  : record at 0x{last['off']:x} rec_len {last['rec_len']} -> "
          f"{min_len}; add '{prop}' at 0x{new_off:x} (rec_len {new_rec_len})")
    assert sum(e["rec_len"] for e in parse_dirents(dirblk)) == BLK, "chain broken"

    # ---- patch 2: the linked inode ----
    vlen = len(value.encode())
    ino = bytearray(itblk[off_in_block:off_in_block + inode_size])
    ino[0x04:0x08] = vlen.to_bytes(4, "little")                    # i_size_lo
    ino[0x1a:0x1c] = (t["links"] + 1).to_bytes(2, "little")        # i_links_count
    itblk[off_in_block:off_in_block + inode_size] = ino
    print(f"  inode: i_size {t['size']} -> {vlen}, i_links_count {t['links']} -> "
          f"{t['links'] + 1}")

    # ---- patch 3: the value ----
    datblk[0:vlen] = value.encode()
    print(f"  data : block {t['block']} <- {value!r}")

    # ---- emit ----
    cmds = []
    for name, blk, data in (("dir", d["block"], dirblk),
                            ("inode", itable_block, itblk),
                            ("data", t["block"], datblk)):
        fn = os.path.join(outdir, f"wo_{blk:012x}.bin")
        with open(fn, "wb") as o:
            o.write(data)
        with open(os.path.join(origdir, f"wo_{blk:012x}.bin"), "wb") as o:
            o.write(origs[name])
        cmds.append(f"wo 0x{PART_OFFSET + blk * BLK:x} 0x{BLK:x} {fn}")
        print(f"  {name:5} -> block {blk:>7}  flash 0x{PART_OFFSET + blk * BLK:x}")

    print()
    print("=== flash commands ===")
    for c in cmds:
        print("  " + c)
    with open(os.path.join(outdir, "commands.txt"), "w") as o:
        o.write("\n".join(cmds) + "\n")

    if "--apply" in sys.argv:
        with open(image, "r+b") as f:
            for blk, data in ((d["block"], dirblk), (itable_block, itblk),
                              (t["block"], datblk)):
                f.seek(blk * BLK)
                f.write(data)
        print(f"\n--apply: patched blocks written into {image} "
              f"(originals saved in {origdir}/)")


if __name__ == "__main__":
    main()
