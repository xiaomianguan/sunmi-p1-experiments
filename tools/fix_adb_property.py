#!/usr/bin/env python3
"""Re-enable adb by repairing persist.sys.usb.config in the live /data blocks.

Context
-------
Toggling "USB debugging" off makes UsbDeviceManager rewrite persist.sys.usb.config
without ",adb". The property service then *recreated* the file, so the dirent now
points at a new inode whose inode-table block and data block we have not read.
Reading them would need two more BROM sessions.

Instead we repoint the existing dirent at an inode we *have* read - the same
allocation-free hard-link trick live_property_patch.py used, applied to a dirent
that already exists:

    dir block    : the 'persist.sys.usb.config' dirent's inode -> the target inode
    inode table  : target inode i_size -> len(value), i_links_count += 1
    data block   : the value at offset 0

Nothing is allocated and no bitmap/group-descriptor/superblock change is needed.
The inode the dirent used to point at is left allocated but unreferenced (the same
benign leak the original patch accepted).

Usage:
  fix_adb_property.py <live_dir> <outdir> [--property=NAME] [--value=VALUE]
                       [--target-inode=N]

<live_dir> must contain dir.bin, itblk.bin and data.bin read by brom_read_live.sh
(dir=655872, itblk=655362, data=the block in wowrites_live/victim.txt).
"""
import os
import sys

BLK = 4096
PART_OFFSET = 0x7A800000
DIR_BLK = 655872
ITB_BLK = 655362
ITB_FIRST_INO = 163201
INODES_PER_BLK = 16
FT_REG_FILE = 1

# which block live/<data-file> holds, and the inode we repoint the dirent at.
# Both are checked against the live inode table, so a stale read is caught here
# instead of being written.
DEFAULT_DATA_BLK = 659973        # brom_read_live.sh: data:0x11ba05000
DEFAULT_DATA_FILE = "data.bin"
DEFAULT_TARGET_INO = 163211      # persist.sys.pq.shp.idx, the original victim


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
        "data": int.from_bytes(r[0x3c:0x40], "little"),   # first extent ee_start_lo
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    live, outdir = args[0], args[1]

    prop = "persist.sys.usb.config"
    value = "mtp,adb"
    target_ino = DEFAULT_TARGET_INO
    data_blk = DEFAULT_DATA_BLK
    data_file = DEFAULT_DATA_FILE
    for a in sys.argv[1:]:
        if a.startswith("--property="):
            prop = a.split("=", 1)[1]
        elif a.startswith("--value="):
            value = a.split("=", 1)[1]
        elif a.startswith("--target-inode="):
            target_ino = int(a.split("=", 1)[1], 0)
        elif a.startswith("--data-block="):
            data_blk = int(a.split("=", 1)[1], 0)
            if data_blk >= PART_OFFSET:      # a flash address was given, not a block
                data_blk = (data_blk - PART_OFFSET) // BLK
        elif a.startswith("--data-file="):
            data_file = a.split("=", 1)[1]

    dirblk = bytearray(open(os.path.join(live, "dir.bin"), "rb").read())
    itblk = bytearray(open(os.path.join(live, "itblk.bin"), "rb").read())
    datblk = bytearray(open(os.path.join(live, data_file), "rb").read())
    for n, b in (("dir.bin", dirblk), ("itblk.bin", itblk), (data_file, datblk)):
        if len(b) != BLK:
            sys.exit(f"!! live/{n} is {len(b)} bytes, expected {BLK}")

    dirents = parse_dirents(dirblk)
    byname = {e["name"].decode(): e for e in dirents}
    if prop not in byname:
        sys.exit(f"!! {prop} is not in the live /property directory - use\n"
                 f"   live_property_patch.py (this tool repairs an existing dirent)")

    e = byname[prop]
    cur_ino = e["inode"]
    if not (ITB_FIRST_INO <= target_ino < ITB_FIRST_INO + INODES_PER_BLK):
        sys.exit(f"!! target inode {target_ino} is not inside inode-table block {ITB_BLK}")
    v = inode_view(itblk, target_ino)

    print(f"live dir block  : {DIR_BLK}  (flash 0x{flash_addr(DIR_BLK):x})")
    print(f"live itable blk : {ITB_BLK}  (flash 0x{flash_addr(ITB_BLK):x})")
    print(f"property        : {prop}")
    print(f"  dirent inode  : {cur_ino}  (its blocks were NOT read - leaving it alone)")
    print(f"  target inode  : {target_ino}  size {v['size']}  links {v['links']}  "
          f"data block {v['data']}")
    print(f"  new value     : {value!r}  (i_size {len(value.encode())})")
    print()

    if v["data"] != data_blk:
        sys.exit(f"!! target inode {target_ino} points at data block {v['data']} "
                 f"(flash 0x{flash_addr(v['data']):x}), but live/{data_file} holds\n"
                 f"   block {data_blk} (flash 0x{flash_addr(data_blk):x}). One of the\n"
                 f"   two reads is stale - re-read and try again. Refusing to write.")
    if cur_ino == target_ino and bytes(datblk[0:v["size"]]) == value.encode():
        print("nothing to do - the dirent already points there with the right value")
        sys.exit(0)

    vlen = len(value.encode())
    dirblk[e["off"]:e["off"] + 4] = target_ino.to_bytes(4, "little")
    itblk[v["off"] + 4:v["off"] + 8] = vlen.to_bytes(4, "little")
    itblk[v["off"] + 0x1a:v["off"] + 0x1c] = (v["links"] + 1).to_bytes(2, "little")
    newdata = bytearray(BLK)
    newdata[0:vlen] = value.encode()

    print(f"  dir   : dirent '{prop}' inode {cur_ino} -> {target_ino} "
          f"(at offset 0x{e['off']:x}, rec_len {e['rec_len']} unchanged)")
    print(f"  inode : {target_ino} i_size {v['size']} -> {vlen}, "
          f"i_links_count {v['links']} -> {v['links'] + 1}")
    print(f"  data  : block {v['data']} <- {value!r}")
    assert sum(x["rec_len"] for x in parse_dirents(dirblk)) == BLK, "chain broken"

    os.makedirs(os.path.join(outdir, "orig"), exist_ok=True)
    cmds = []
    for name, blk, data in (("dir", DIR_BLK, dirblk),
                            ("itblk", ITB_BLK, itblk),
                            ("data", v["data"], newdata)):
        fn = os.path.join(outdir, f"wo_{blk:012x}.bin")
        open(fn, "wb").write(data)
        cmds.append(f"wo 0x{flash_addr(blk):x} 0x{BLK:x} {fn}")
        print(f"  {name:6} -> block {blk:>7}  flash 0x{flash_addr(blk):x}")

    open(os.path.join(outdir, "orig", f"wo_{DIR_BLK:012x}.bin"), "wb").write(dirblk)
    open(os.path.join(outdir, "orig", f"wo_{ITB_BLK:012x}.bin"), "wb").write(itblk)
    open(os.path.join(outdir, "orig", f"wo_{v['data']:012x}.bin"), "wb").write(datblk)
    open(os.path.join(outdir, "commands.txt"), "w").write("\n".join(cmds) + "\n")
    with open(os.path.join(outdir, "victim.txt"), "w") as o:
        o.write(f"{v['data']} 0x{flash_addr(v['data']):x} {prop} {target_ino}\n")
    print()
    print(f"payloads + exact rollback in {outdir}/ (and {outdir}/orig/)")


if __name__ == "__main__":
    main()
