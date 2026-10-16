#!/usr/bin/env python3
"""Work out the link/load base address of an MTK LK (lk.bin) raw image.

An MTK image has a small header, then raw ARM code. Code references strings via
literal pools: `LDR Rn, [PC, #imm]` where the pool word is the absolute VA of the
string. So if we know a string's offset inside the file, we can scan every 4-byte
word in the code for `word - string_offset == candidate_base` and recover the base.

Usage: lk_base.py dumps/lk.bin
"""
import collections
import struct
import sys

# MTK image header is 512 bytes; the payload follows.
HEADER = 0x200


def is_string_at(data, off, minlen=4):
    if off < 0 or off + minlen >= len(data):
        return False
    c = data[off]
    if not (0x20 <= c < 0x7F):
        return False
    n = 0
    while off + n < len(data) and 0x20 <= data[off + n] < 0x7F:
        n += 1
        if n > 200:
            break
    return n >= minlen


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "dumps/lk.bin"
    data = open(path, "rb").read()
    print(f"file: {path}  size: {len(data)} bytes (0x{len(data):x})")

    magic, size = struct.unpack_from("<II", data, 0)
    name = data[8:20].split(b"\x00")[0].decode("ascii", "replace")
    print(f"MTK header: magic=0x{magic:08x} size=0x{size:x} name={name!r}")

    code_start = HEADER
    code_end = min(len(data), HEADER + size)
    print(f"code region: 0x{code_start:x} .. 0x{code_end:x}")

    # Collect offsets of interesting strings inside the file.
    targets = {}
    for s in (b"AND_SECCFG_v", b"Bootimg verify failed", b"dump lock_state, %x",
              b"Unlock operation is not allowed", b"SECLIB_IMG_VERIFY"):
        i = data.find(s)
        if i >= 0:
            targets[s.decode()] = i
    print("string offsets:", {k: hex(v) for k, v in targets.items()})

    votes = collections.Counter()
    for soff in targets.values():
        for off in range(code_start, code_end - 4, 4):
            (w,) = struct.unpack_from("<I", data, off)
            base = w - soff
            # plausible ARM DRAM bases for MTK
            if 0x40000000 <= base <= 0x90000000 and base % 0x1000 == 0:
                votes[base] += 1

    print()
    print("candidate bases (votes, base, #string-word refs):")
    for base, v in votes.most_common(12):
        # sanity: how many pool words point at printable strings with this base?
        hits = 0
        for off in range(code_start, code_end - 4, 4):
            (w,) = struct.unpack_from("<I", data, off)
            t = w - base
            if 0 <= t < len(data) and is_string_at(data, t, 4):
                hits += 1
        print(f"  0x{base:08x}  votes={v:4d}  string_pool_hits={hits}")


if __name__ == "__main__":
    main()
