#!/usr/bin/env python3
"""Build the dm-verity "logging mode" patch block for the Sunmi P1's /system.

Why this works (verified against AOSP 6.0.1 fs_mgr_verity.c and against the
device's own /system image):

  * /system is mounted from /dev/block/dm-0, i.e. dm-verity is enforcing.
  * The dm-verity table + signature live in a 32 KB metadata block that starts
    at the *end of the ext4 filesystem*: offset 0x5F3DF000 on this ROM
    (magic 0xb001b001 = VERITY_METADATA_MAGIC_NUMBER).
  * That block is OUTSIDE the hashed filesystem, so writing it cannot break
    the verity signature.
  * Inside it, offset +0x4000 is the "metadata area" ("skip cryptfs metadata
    area"): a tiny text TLV list introduced by magic 0x01564c54, holding tags
    named "<tag>_<mountpoint>", terminated by "eod 0".
  * fs_mgr_load_verity_state() -> read_verity_state() reads a 12-byte
    struct verity_state { uint32 header; uint32 version; int32 mode; } from the
    data area of the tag "verity_state_system".
  * mode 1 == VERITY_MODE_LOGGING -> load_verity_table() passes
    ignore_corruption to dm-verity, so a modified /system still mounts.
    (mode 2 == VERITY_MODE_DEFAULT == restart_on_corruption == current state.)

On this ROM the metadata area has never been initialised (no 0x01564c54), so
fs_mgr itself creates the tag and writes VERITY_MODE_DEFAULT into it. We
pre-write it with VERITY_MODE_LOGGING instead; read_verity_state() then accepts
it (header ok, version ok, 0 <= mode <= VERITY_MODE_LAST) and leaves it alone.

The one 4 KB block we must rewrite is fs offset 0x5F3E3000, which maps to
physical 0x69BE3000 (system partition base 0x0A800000 from the GPT).
"""
import hashlib
import struct
import sys

SYS_DUMP = "/home/puffercat/sunmi-p1-experiments/dumps/system.bin"
OUT_DIR = "/home/puffercat/sunmi-p1-experiments/verity_disable"

SYSTEM_BASE = 0x0A800000          # from dumps/gpt.bin
FS_SIZE = 0x5F3DF000              # ext4 s_blocks_count * block_size (verified)
META_OFF = FS_SIZE                # start of the 32 KB verity metadata block
METADATA_AREA = 0x4000            # "skip cryptfs metadata area"
TLV_BLOCK = META_OFF + METADATA_AREA      # 0x5F3E3000
PHYS_ADDR = SYSTEM_BASE + TLV_BLOCK       # 0x69BE3000

METADATA_MAGIC = 0x01564c54
VERITY_STATE_HEADER = 0x83c0ae9d
VERITY_STATE_VERSION = 1
VERITY_MODE_LOGGING = 1           # enum verity_mode, fs_mgr/include/fs_mgr.h
VERITY_MODE_DEFAULT = 2
BLOCK = 4096


def build(mode):
    f = open(SYS_DUMP, "rb")

    # ---- the signed verity footer: magic, protocol, 256-byte RSA signature ----
    f.seek(META_OFF)
    head = f.read(8 + 256)
    magic, proto = struct.unpack_from("<II", head, 0)
    assert magic == 0xB001B001, "no verity footer at 0x%X" % META_OFF
    assert proto == 0, "unexpected verity protocol version %d" % proto
    signature = head[8:8 + 256]

    # compare_last_signature() computes SHA256_hash(signature, RSANUMBYTES, curr)
    # and compares it against the "verity_lastsig_<mnt>" tag. If they differ (or
    # the tag is absent) fs_mgr RESETS the state to VERITY_MODE_DEFAULT, which
    # would silently undo our patch - so we pre-seed the tag with the correct
    # hash of the current signature.
    lastsig = hashlib.sha256(signature).digest()

    # ---- the metadata TLV area we are about to write ----
    # work on the whole 32 KB metadata block, then emit only the 4 KB window
    # that starts at METADATA_AREA (that window is one flash block).
    f.seek(META_OFF)
    meta = bytearray(f.read(32768))
    assert len(meta) == 32768, "short read"
    assert meta[METADATA_AREA:METADATA_AREA + 4] == b"\x00\x00\x00\x00", \
        "TLV area is not empty: %r" % bytes(meta[METADATA_AREA:METADATA_AREA + 16])

    blk = meta                     # index directly by 32 KB offset

    off = METADATA_AREA
    struct.pack_into("<I", blk, off, METADATA_MAGIC)
    off += 4

    # tag 1: the mode we want
    line = b"verity_state_system %d\n" % struct.calcsize("<III")
    blk[off:off + len(line)] = line
    off += len(line)
    state_off = off                       # fs_mgr pread()s the struct here
    struct.pack_into("<III", blk, off, VERITY_STATE_HEADER,
                     VERITY_STATE_VERSION, mode)
    off += struct.calcsize("<III")

    # tag 2: hash of the current signature, so the state is not reset
    line = b"verity_lastsig_system %d\n" % len(lastsig)
    blk[off:off + len(line)] = line
    off += len(line)
    blk[off:off + len(lastsig)] = lastsig
    off += len(lastsig)

    blk[off:off + 6] = b"eod 0\n"
    # emit only the 4 KB flash block that carries the TLV area
    return bytearray(meta[METADATA_AREA:METADATA_AREA + BLOCK]), state_off, lastsig


def main():
    mode = VERITY_MODE_LOGGING
    if len(sys.argv) > 1 and sys.argv[1] == "--mode-default":
        mode = VERITY_MODE_DEFAULT

    blk, state_off, lastsig = build(mode)

    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    path = "%s/blk_0x%08X.bin" % (OUT_DIR, TLV_BLOCK)
    with open(path, "wb") as f:
        f.write(blk)

    # rollback copy: the pristine block as read from the 17:57 dump
    with open(SYS_DUMP, "rb") as f:
        f.seek(TLV_BLOCK)
        orig = f.read(BLOCK)
    rollback = "%s/orig_blk_0x%08X.bin" % (OUT_DIR, TLV_BLOCK)
    with open(rollback, "wb") as f:
        f.write(orig)

    print("mode                 = %d (%s)" % (
        mode, "VERITY_MODE_LOGGING" if mode == 1 else "VERITY_MODE_DEFAULT"))
    print("fs offset            = 0x%08X" % TLV_BLOCK)
    print("physical flash addr  = 0x%08X" % PHYS_ADDR)
    print("state struct offset  = block+0x%X" % state_off)
    print("lastsig              = %s" % lastsig.hex())
    print("payload              = %s (%d bytes)" % (path, len(blk)))
    print("rollback copy        = %s" % rollback)
    print()
    print("patched TLV area (offset within the 4 KB block):")
    for i in range(0, 0x80, 16):
        print("  +0x%04X  %s" % (i, blk[i:i + 16].hex(" ")))
    print()
    print("as text:")
    print("  " + repr(bytes(blk[:64])))


if __name__ == "__main__":
    main()
