#!/usr/bin/env python3
"""Diff two images, extract the changed regions, and emit flash-write commands.

Usage: diff_extract.py <original> <modified> <outdir>

Writes one payload file per contiguous run of changed 4 KB blocks and prints the
matching `wo <flash_offset> <length> <file>` commands (userdata partition base
0x7A800000).
"""
import os
import sys

PART_OFFSET = 0x7A800000
BLK = 4096
CHUNK = 1 << 20


def main():
    a_path, b_path, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(outdir, exist_ok=True)

    changed = []
    with open(a_path, "rb") as a, open(b_path, "rb") as b:
        ci = 0
        while True:
            x = a.read(CHUNK)
            y = b.read(CHUNK)
            if not x and not y:
                break
            if x != y:
                n = max(len(x), len(y))
                for off in range(0, n, BLK):
                    if x[off:off + BLK] != y[off:off + BLK]:
                        changed.append((ci * CHUNK + off) // BLK)
            ci += 1

    if not changed:
        print("no differences")
        return

    runs = []
    for c in changed:
        if runs and c == runs[-1][1] + 1:
            runs[-1][1] = c
        else:
            runs.append([c, c])

    print(f"{len(changed)} blocks differ, in {len(runs)} contiguous run(s)")
    print()

    cmds = []
    with open(b_path, "rb") as f:
        for lo, hi in runs:
            nb = hi - lo + 1
            f.seek(lo * BLK)
            data = f.read(nb * BLK)
            fn = os.path.join(outdir, f"wo_{lo * BLK:012x}.bin")
            with open(fn, "wb") as o:
                o.write(data)
            off = PART_OFFSET + lo * BLK
            cmds.append(f"wo 0x{off:x} 0x{nb * BLK:x} {fn}")
            print(f"  blocks {lo}..{hi}  ({nb} blk / {nb * BLK} B)  "
                  f"flash offset 0x{off:x}")

    print()
    print("=== flash write commands ===")
    for c in cmds:
        print("  " + c)
    with open(os.path.join(outdir, "commands.txt"), "w") as o:
        o.write("\n".join(cmds) + "\n")
    print()
    print(f"commands saved to {outdir}/commands.txt")


if __name__ == "__main__":
    main()
