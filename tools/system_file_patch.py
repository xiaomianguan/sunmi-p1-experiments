#!/usr/bin/env python3
"""In-place, same-length edit of a file inside the /system ext4 image.

Resolves the file's extents with debugfs (working directly on the partition
dump), then emits the whole 4 KB flash block(s) that need rewriting together
with their absolute flash addresses, ready for `mtk wo <addr> 0x1000 <file>`.

Only same-length replacements are allowed.  That keeps the file size, its inode
and its extent tree untouched, so nothing but file *content* changes - which is
exactly what we want both for surgical property edits and for proving that
dm-verity is now ignoring corruption.

Usage:
    system_file_patch.py <path-in-fs> <old-string> <new-string> [--outdir DIR]
    system_file_patch.py /build.prop ro.xc_delete_advanced_item=1 ro.xc_delete_advanced_item=0
"""
import os
import re
import struct
import subprocess
import sys

DUMP = "/home/puffercat/sunmi-p1-experiments/dumps/system.bin"
SYSTEM_BASE = 0x0A800000          # GPT entry for 'system'
BLOCK = 4096


def debugfs(args):
    r = subprocess.run(["debugfs", "-R", args, DUMP],
                       capture_output=True)
    return r.stdout


def extents(path):
    """Return [(logical_block, physical_block, count), ...] for a file."""
    out = debugfs("stat %s" % path).decode("ascii", "replace")
    m = re.search(r"EXTENTS:\s*\n(.*?)\n\n", out, re.S)
    if not m:
        m = re.search(r"EXTENTS:\s*\n(.*)", out, re.S)
    if not m:
        raise SystemExit("!! could not parse EXTENTS for %s\n%s" % (path, out))
    ents = []
    for mm in re.finditer(r"\((\d+)(?:-(\d+))?\):(\d+)(?:-(\d+))?",
                          m.group(1)):
        l0 = int(mm.group(1))
        l1 = int(mm.group(2)) if mm.group(2) else l0
        p0 = int(mm.group(3))
        ents.append((l0, p0, l1 - l0 + 1))
    if not ents:
        raise SystemExit("!! no extents parsed for %s\n%s" % (path, out))
    return ents


def main():
    path = sys.argv[1]
    pairs = []
    rest = sys.argv[2:]
    if "--outdir" in rest:
        i = rest.index("--outdir")
        outdir = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if len(rest) % 2:
        raise SystemExit("!! edits must be <old> <new> pairs")
    for i in range(0, len(rest), 2):
        pairs.append((rest[i].encode(), rest[i + 1].encode()))

    data = debugfs("cat %s" % path)
    ents = extents(path)
    print("file      : %s" % path)
    print("extents   : %s" % ents)

    # apply every edit to the 4 KB blocks that hold them
    blocks = {}
    for old, new in pairs:
        if len(old) != len(new):
            raise SystemExit("!! %r -> %r changes length" % (old, new))
        idx = data.find(old)
        if idx < 0:
            raise SystemExit("!! %r not found in %s" % (old, path))
        log_block, off_in_block = divmod(idx, BLOCK)
        if off_in_block + len(old) > BLOCK:
            raise SystemExit("!! %r straddles a block boundary" % old)
        phys = None
        for l0, p0, cnt in ents:
            if l0 <= log_block < l0 + cnt:
                phys = p0 + (log_block - l0)
                break
        if phys is None:
            raise SystemExit("!! byte %d not inside any extent" % idx)
        print("  edit %r -> %r  (file byte %d, fs block %d)"
              % (old, new, idx, phys))
        if phys not in blocks:
            with open(DUMP, "rb") as f:
                f.seek(phys * BLOCK)
                blocks[phys] = bytearray(f.read(BLOCK))
        assert blocks[phys][off_in_block:off_in_block + len(old)] == old
        blocks[phys][off_in_block:off_in_block + len(new)] = new

    os.makedirs(outdir, exist_ok=True)
    print()
    print("payloads to flash:")
    for phys, blk in sorted(blocks.items()):
        addr = SYSTEM_BASE + phys * BLOCK
        out = "%s/blk_fs%08X.bin" % (outdir, phys * BLOCK)
        with open(out, "wb") as f:
            f.write(blk)
        print("  mtk wo 0x%x 0x1000 %s" % (addr, out))


if __name__ == "__main__":
    main()
