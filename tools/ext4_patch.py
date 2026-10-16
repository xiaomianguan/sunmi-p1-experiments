#!/usr/bin/env python3
"""Patch a file inside an ext4 image in place, then emit the minimal set of
flash-write commands needed to apply it on the device.

Designed for same-length value flips (e.g. value="0" -> value="1"), so the file
size never changes, no inode/bitmap/journal metadata is touched, and only a couple
of 4 KB data blocks need rewriting. This filesystem has METADATA_CSUM off, so even
a size change would not need a checksum fix, but we still prefer same-length.

Usage:
  ext4_patch.py <image> <file-in-image> <old> <new> [<old2> <new2> ...]

Example:
  ext4_patch.py dumps/userdata.bin /system/users/0/settings_global.xml \
      'name="adb_enabled" value="0"' 'name="adb_enabled" value="1"'
"""
import os
import re
import shutil
import subprocess
import sys

PART_OFFSET = 0x7A800000          # userdata partition offset in flash
BLOCK_SIZE = 4096


def blocks_of(image, path):
    out = subprocess.run(["debugfs", "-R", f"blocks {path}", image],
                         capture_output=True, text=True).stdout
    nums = [int(x) for x in re.findall(r"\d+", out)]
    return nums


def main():
    if len(sys.argv) < 5 or (len(sys.argv) - 3) % 2 != 0:
        print(__doc__)
        sys.exit(1)
    image, path = sys.argv[1], sys.argv[2]
    pairs = list(zip(sys.argv[3::2], sys.argv[4::2]))

    for old, new in pairs:
        if len(old) != len(new):
            print(f"!! not same length: {old!r} vs {new!r}")
            sys.exit(1)

    print(f"image : {image}")
    print(f"file  : {path}")
    print()

    # read the current file contents
    tmp = "/tmp/ext4_patch_cur.bin"
    subprocess.run(["debugfs", "-R", f"dump {path} {tmp}", image],
                   capture_output=True, text=True)
    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        print("!! could not extract the file (wrong path, or missing)")
        sys.exit(1)
    content = bytearray(open(tmp, "rb").read())
    orig_len = len(content)
    print(f"file size: {orig_len} bytes")

    for old, new in pairs:
        ob, nb = old.encode(), new.encode()
        n = content.count(ob)
        print(f"  {ob!r} -> {nb!r}   occurrences: {n}")
        if n == 0:
            print("  !! pattern not found - aborting")
            sys.exit(1)
        content = bytearray(content.replace(ob, nb))

    assert len(content) == orig_len, "length changed - refusing (inode would need editing)"

    blks = blocks_of(image, path)
    needed = (orig_len + BLOCK_SIZE - 1) // BLOCK_SIZE
    print(f"\nblocks  : {[hex(b) for b in blks[:needed]]}")
    if len(blks) < needed:
        print("!! block list shorter than file - aborting")
        sys.exit(1)

    # Instead of copying the whole 5.35 GB image, save the ORIGINAL contents of
    # only the blocks we are about to change. That is a few KB and is all we need
    # to roll back (write them back with the same `wo` commands).
    rbdir = image + ".rollback"
    os.makedirs(rbdir, exist_ok=True)

    changed = []
    with open(image, "r+b") as f:
        for i in range(needed):
            blk = blks[i]
            base = blk * BLOCK_SIZE
            f.seek(base)
            cur = f.read(BLOCK_SIZE)
            new = content[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]
            new = new + bytes(BLOCK_SIZE - len(new)) if len(new) < BLOCK_SIZE else new
            new = new[:BLOCK_SIZE]
            if cur != new:
                # save original block for rollback
                open(os.path.join(rbdir, f"{base:012x}.bin"), "wb").write(cur)
                f.seek(base)
                f.write(new)
                changed.append(base)
                print(f"  wrote block {blk} (image offset 0x{base:x})")

    print()
    if not changed:
        print("nothing changed?")
        return

    # emit flash write commands for the changed blocks
    print("=== flash write commands (run in a BROM session) ===")
    for base in changed:
        fn = f"/tmp/wo_{base:x}.bin"
        with open(image, "rb") as f:
            f.seek(base)
            data = f.read(BLOCK_SIZE)
        open(fn, "wb").write(data)
        print(f"  wo 0x{PART_OFFSET + base:x} 0x{BLOCK_SIZE:x} {fn}")


if __name__ == "__main__":
    main()
