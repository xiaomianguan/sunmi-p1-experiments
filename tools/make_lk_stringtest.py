#!/usr/bin/env python3
"""Prepare a harmless string-patched lk.bin to answer one question:

    Does the PRELOADER verify the LK image?

Evidence so far says NO (lk.bin carries no appended signature, unlike boot.img
which does), which would mean we can flash a patched LK. This patch changes ONLY
the boot-menu banner text, so if the device still boots and the menu shows the new
text, we have proof that a modified LK is accepted and executed.

  "Select Boot Mode:"  ->  "***LK PATCHED***:"     (same length, colon kept)

Nothing functional is altered: same size, same code, one string.
"""
import shutil
import sys

SRC = "dumps/lk.bin"
DST = "lk_patched_test.img"

data = bytearray(open(SRC, "rb").read())

OLD = b"Select Boot Mode:"
NEW = b"***LK PATCHED***:"
assert len(OLD) == len(NEW) == 17, (len(OLD), len(NEW))

n = data.count(OLD)
print(f"occurrences of {OLD!r}: {n}")
assert n == 1, "string is not unique - aborting"

off = data.find(OLD)
data[off:off + len(OLD)] = NEW
print(f"patched at file offset 0x{off:x}")

open(DST, "wb").write(bytes(data))
print(f"wrote {DST} ({len(data)} bytes)")
print()
print("Differences from stock lk.bin:")
a = open(SRC, "rb").read()
diff = [i for i in range(len(a)) if a[i] != data[i]]
print(f"  {len(diff)} byte(s) differ at {[hex(x) for x in diff]}")
print()
print("To test:")
print("  ./brom_write.sh lk lk_patched_test.img verify")
print("  then boot with Volume Up held - the boot menu should read")
print("  '***LK PATCHED***:' instead of 'Select Boot Mode:'")
