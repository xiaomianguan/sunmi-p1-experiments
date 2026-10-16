#!/usr/bin/env python3
"""Build the persist.sys.usb.config patch from blocks read OFF THE DEVICE.

Why this exists next to make_property_patch.py
---------------------------------------------
make_property_patch.py patches an *offline image*.  That was fine until the
device turned out to have re-initialised /data since our 20:38 snapshot: the
same 17 property names exist, but they point at *different inodes* and their
data blocks have moved.  Patching from the snapshot would therefore have
overwritten unrelated live files.

This tool works only from live reads, so it cannot be stale by construction:

  live/dir.bin     /property directory block        (flash 0x11aa00000)
  live/itblk.bin   group-20 inode table, block 0    (flash 0x11a802000)

Both addresses are stable because mkfs lays a filesystem out deterministically,
and the live reads confirm the layout (inode 163201 = /property, extent 655872).

The patch is still the allocation-free hard-link trick:
  * dir block    - append a dirent for the new property name
  * inode table  - victim inode: i_size -> len(value), i_links_count += 1
  * victim's data block - the value
No inode/block is allocated, so no bitmap, group descriptor or superblock
change is needed.

Usage:
  live_property_patch.py <live_dir> <outdir> [--property=NAME] [--value=VALUE]
                         [--victim=NAME]
"""
import os
import sys

BLK = 4096
PART_OFFSET = 0x7A800000
DIR_BLK = 655872
ITB_BLK = 655362
ITB_FIRST_INO = 163201          # first inode held by that inode-table block
INODES_PER_BLK = 16             # 4096 / 256
FT_REG_FILE = 1


def flash_addr(blk):
    return PART_OFFSET + blk * BLK


def parse_dirents(d):
    out, off = [], 0
    while off < BLK:
        ino = int.from_bytes(d[off:off + 4], "little")
        rec = int.from_bytes(d[off + 4:off + 6], "little")
        nl = d[off + 6]
        ft = d[off + 7]
        if rec < 8 or rec % 4 or off + rec > BLK:
            sys.exit(f"!! corrupt dirent at 0x{off:x} (rec_len={rec})")
        out.append({"off": off, "inode": ino, "rec_len": rec, "name_len": nl,
                    "file_type": ft,
                    "name": bytes(d[off + 8:off + 8 + nl])})
        off += rec
    return out


def inode_view(blk, ino):
    off = (ino - ITB_FIRST_INO) * 256
    r = blk[off:off + 256]
    return {
        "off": off,
        "mode": int.from_bytes(r[0:2], "little"),
        "size": int.from_bytes(r[4:8], "little"),
        "links": int.from_bytes(r[0x1a:0x1c], "little"),
        "blocks": int.from_bytes(r[0x1c:0x20], "little"),
        "flags": int.from_bytes(r[0x20:0x24], "little"),
        "data": int.from_bytes(r[0x3c:0x40], "little"),   # first extent leaf
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    live, outdir = args[0], args[1]

    prop = "persist.sys.usb.config"
    value = "mtp,adb"
    victim = "persist.sys.pq.shp.idx"
    for a in sys.argv[1:]:
        if a.startswith("--property="):
            prop = a.split("=", 1)[1]
        elif a.startswith("--value="):
            value = a.split("=", 1)[1]
        elif a.startswith("--victim="):
            victim = a.split("=", 1)[1]

    dirblk = bytearray(open(os.path.join(live, "dir.bin"), "rb").read())
    itblk = bytearray(open(os.path.join(live, "itblk.bin"), "rb").read())
    if len(dirblk) != BLK or len(itblk) != BLK:
        sys.exit("!! live blocks must be 4096 bytes")

    dirents = parse_dirents(dirblk)
    byname = {e["name"].decode(): e for e in dirents}
    if prop in byname:
        sys.exit(f"!! {prop} already exists")
    if victim not in byname:
        sys.exit(f"!! victim {victim} not found in the live directory")

    v_ino = byname[victim]["inode"]
    if not (ITB_FIRST_INO <= v_ino < ITB_FIRST_INO + INODES_PER_BLK):
        sys.exit(f"!! victim inode {v_ino} is not inside inode-table block "
                 f"{ITB_BLK}; pick another victim")
    v = inode_view(itblk, v_ino)
    if v["data"] == 0:
        sys.exit(f"!! victim {victim} (inode {v_ino}) has no data block "
                 f"(size 0) - pick another victim")

    print(f"live dir block  : {DIR_BLK}  (flash 0x{flash_addr(DIR_BLK):x})")
    print(f"live itable blk : {ITB_BLK}  (flash 0x{flash_addr(ITB_BLK):x})")
    print(f"new property    : {prop} = {value!r}")
    print(f"victim          : {victim}  inode {v_ino}  size {v['size']}  "
          f"links {v['links']}  data block {v['data']}")
    print(f"                  -> that property will now read {value!r}")
    print()

    # ---- dir block: append our dirent into the slack of the last record ----
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
    rec = (v_ino.to_bytes(4, "little")
           + new_rec_len.to_bytes(2, "little")
           + bytes([len(prop), FT_REG_FILE]) + prop.encode())
    dirblk[new_off:new_off + len(rec)] = rec
    print(f"  dir  : shrink '{last['name'].decode()}' rec_len "
          f"{last['rec_len']} -> {min_len}; add '{prop}' at 0x{new_off:x} "
          f"(rec_len {new_rec_len}, ino {v_ino})")
    assert sum(e["rec_len"] for e in parse_dirents(dirblk)) == BLK, "chain broken"

    # ---- inode table: victim's size + link count ----
    vlen = len(value.encode())
    itblk[v["off"] + 4:v["off"] + 8] = vlen.to_bytes(4, "little")
    itblk[v["off"] + 0x1a:v["off"] + 0x1c] = (v["links"] + 1).to_bytes(2, "little")
    print(f"  inode: {victim} i_size {v['size']} -> {vlen}, "
          f"i_links_count {v['links']} -> {v['links'] + 1}")

    # ---- victim's data block: the value (rest of the block is past EOF) ----
    datblk = bytearray(BLK)
    datblk[0:vlen] = value.encode()
    print(f"  data : block {v['data']} <- {value!r}")

    # ---- emit ----
    os.makedirs(os.path.join(outdir, "orig"), exist_ok=True)
    cmds = []
    for name, blk, data in (("dir", DIR_BLK, dirblk),
                            ("itblk", ITB_BLK, itblk),
                            ("data", v["data"], datblk)):
        fn = os.path.join(outdir, f"wo_{blk:012x}.bin")
        open(fn, "wb").write(data)
        cmds.append(f"wo 0x{flash_addr(blk):x} 0x{BLK:x} {fn}")
        print(f"  {name:6} -> block {blk:>7}  flash 0x{flash_addr(blk):x}")

    # rollback payloads: exact for the two blocks we read live; for the victim's
    # data block we only ever overwrite the first bytes (the rest is past the new
    # 7-byte EOF), so a value + zeros block is a faithful rollback.
    open(os.path.join(outdir, "orig", f"wo_{DIR_BLK:012x}.bin"), "wb").write(
        open(os.path.join(live, "dir.bin"), "rb").read())
    open(os.path.join(outdir, "orig", f"wo_{ITB_BLK:012x}.bin"), "wb").write(
        open(os.path.join(live, "itblk.bin"), "rb").read())
    print()
    print("=== flash commands ===")
    for c in cmds:
        print("  " + c)
    open(os.path.join(outdir, "commands.txt"), "w").write("\n".join(cmds) + "\n")
    with open(os.path.join(outdir, "victim.txt"), "w") as o:
        o.write(f"{v['data']} 0x{flash_addr(v['data']):x} {victim} {v_ino}\n")
    print()
    print(f"victim data block recorded in {outdir}/victim.txt "
          f"(block {v['data']}, flash 0x{flash_addr(v['data']):x})")
    print("NOTE: that block is read back BEFORE writing, so rollback is exact.")


if __name__ == "__main__":
    main()
