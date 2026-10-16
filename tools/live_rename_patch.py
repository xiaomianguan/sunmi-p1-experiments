#!/usr/bin/env python3
"""Create persist.sys.usb.config by RENAMING an existing property file's dirent.

Why rename, and not add a dirent
--------------------------------
Android's property service rewrites a persistent property file with
  write(tempfile); rename(tempfile, path)
so **every** file in /data/property gets a fresh inode at every boot (verified
on this device: all 16 ctimes land in a ~20s window during early boot, and the
name->inode mapping is permuted on every boot).

That kills the earlier "hard link to an existing inode" trick: the victim's
inode is freed by its own rename and our extra dirent ends up pointing at a
dead inode.

Renaming is immune to this, because we are not adding anything - we are
*replacing the name* of an existing, fully-allocated file.  Pick a victim whose
name is the SAME LENGTH as the new property name, and the edit is a pure
in-place write of the name bytes: rec_len, name_len, the inode number and the
file type all stay identical, so no block/inode is allocated and no bitmap,
group descriptor or superblock field changes.

At the next boot the property service reads our file, sets
`persist.sys.usb.config=mtp,adb`, and then persists it itself - after which the
value survives on its own.

Cost: the victim's own property disappears (e.g. persist.sys.pq.shp.idx, a
display-sharpness index read as an int -> default 0).  Harmless.

Usage:
  live_rename_patch.py <live_dir> <outdir> [--victim=NAME]
                       [--property=NAME] [--value=VALUE]

Reads (live, must be current):
  <live_dir>/dir.bin     /property directory block       flash 0x11aa00000
  <live_dir>/itblk.bin   group-20 inode table block 0    flash 0x11a802000
"""
import os
import sys

BLK = 4096
PART_OFFSET = 0x7A800000
DIR_BLK = 655872
ITB_BLK = 655362
ITB_FIRST_INO = 163201
INODES_PER_BLK = 16


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
    return {"off": off,
            "mode": int.from_bytes(r[0:2], "little"),
            "size": int.from_bytes(r[4:8], "little"),
            "links": int.from_bytes(r[0x1a:0x1c], "little"),
            "data": int.from_bytes(r[0x3c:0x40], "little")}


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
        sys.exit(f"!! {prop} already exists in the live directory")
    if victim not in byname:
        sys.exit(f"!! victim {victim} not found in the live directory")
    if len(victim) != len(prop):
        sys.exit(f"!! name lengths differ: victim {len(victim)} vs new "
                 f"{len(prop)} - a rename would change rec_len. Pick a victim "
                 f"with exactly {len(prop)} characters.")

    e = byname[victim]
    v_ino = e["inode"]
    if not (ITB_FIRST_INO <= v_ino < ITB_FIRST_INO + INODES_PER_BLK):
        sys.exit(f"!! victim inode {v_ino} is not in inode-table block {ITB_BLK}")
    v = inode_view(itblk, v_ino)
    if v["data"] == 0:
        sys.exit(f"!! victim {victim} has no data block - pick another victim")
    if v["links"] != 1:
        sys.exit(f"!! victim has links={v['links']}, expected 1")

    print(f"live dir block  : {DIR_BLK}  (flash 0x{flash_addr(DIR_BLK):x})")
    print(f"live itable blk : {ITB_BLK}  (flash 0x{flash_addr(ITB_BLK):x})")
    print(f"rename          : {victim!r} -> {prop!r}   "
          f"({len(victim)} == {len(prop)} chars, rec_len stays {e['rec_len']})")
    print(f"value           : {value!r}")
    print(f"victim inode    : {v_ino}  size {v['size']}  links {v['links']}  "
          f"data block {v['data']}")
    print(f"                  -> {victim} disappears; {prop} takes its inode")
    print()

    # ---- dir block: rewrite just the 22 name bytes ----
    old_name = e["name"]
    new_name = prop.encode()
    assert len(old_name) == len(new_name)
    dirblk[e["off"] + 8:e["off"] + 8 + len(new_name)] = new_name
    changed = sum(1 for i in range(len(new_name))
                  if old_name[i] != new_name[i])
    print(f"  dir  : dirent at 0x{e['off']:x}, name_len {e['name_len']} "
          f"unchanged, rec_len {e['rec_len']} unchanged, "
          f"inode {v_ino} unchanged ({changed} name bytes differ)")
    assert sum(x["rec_len"] for x in parse_dirents(dirblk)) == BLK

    # ---- inode: only the size ----
    vlen = len(value.encode())
    itblk[v["off"] + 4:v["off"] + 8] = vlen.to_bytes(4, "little")
    print(f"  inode: i_size {v['size']} -> {vlen}  (i_links stays {v['links']})")

    # ---- data block ----
    datblk = bytearray(BLK)
    datblk[0:vlen] = value.encode()
    print(f"  data : block {v['data']} <- {value!r}")

    os.makedirs(os.path.join(outdir, "orig"), exist_ok=True)
    cmds = []
    for name, blk, data in (("dir", DIR_BLK, dirblk),
                            ("itblk", ITB_BLK, itblk),
                            ("data", v["data"], datblk)):
        fn = os.path.join(outdir, f"wo_{blk:012x}.bin")
        open(fn, "wb").write(data)
        cmds.append(f"wo 0x{flash_addr(blk):x} 0x{BLK:x} {fn}")
        print(f"  {name:6} -> block {blk:>7}  flash 0x{flash_addr(blk):x}")

    open(os.path.join(outdir, "orig", f"wo_{DIR_BLK:012x}.bin"), "wb").write(
        open(os.path.join(live, "dir.bin"), "rb").read())
    open(os.path.join(outdir, "orig", f"wo_{ITB_BLK:012x}.bin"), "wb").write(
        open(os.path.join(live, "itblk.bin"), "rb").read())
    open(os.path.join(outdir, "victim.txt"), "w").write(
        f"{v['data']} 0x{flash_addr(v['data']):x} {victim} {v_ino}\n")

    print()
    print("=== flash commands ===")
    for c in cmds:
        print("  " + c)
    open(os.path.join(outdir, "commands.txt"), "w").write("\n".join(cmds) + "\n")
    print()
    print(f"victim data block {v['data']} recorded in {outdir}/victim.txt")
    print("That block is read back BEFORE writing, so rollback is exact.")


if __name__ == "__main__":
    main()
