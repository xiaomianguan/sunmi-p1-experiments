#!/usr/bin/env python3
"""Build an LK image whose kernel cmdline disables dm-verity enforcement.

Why: on this ROM the dm-verity *mode* cannot be changed any other way.

  * /system is verity-protected (fstab "verify", mounted from /dev/block/dm-0).
  * The AOSP 6 state mechanism is unusable here: fstab->verity_loc is NULL
    (the fstab says bare "verify", and verity_loc is only set from an option
    that carries a path), so metadata_find() bails and fs_mgr falls back to
    VERITY_MODE_EIO == enforcing.
  * Sunmi/MTK also commented out verity_load_state / verity_update_state in
    init.rc, so the TLV area is never even initialised (verified: the block
    read back from the device was all zeros).
  * "adb disable-verity" refuses: user build, ALLOW_ADBD_DISABLE_VERITY is not
    compiled in.

That leaves the kernel cmdline, which LK builds.  fs_mgr's load_verity_state()
starts with:

    property_get("ro.boot.veritymode", propbuf, "");
    if (!strcmp(propbuf, "logging")) { *mode = VERITY_MODE_LOGGING; return 0; }

and VERITY_MODE_LOGGING makes load_verity_table() pass "ignore_corruption" to
dm-verity, so a modified /system mounts and reads.

The LK cmdline string sits at file offset 0x3C63C and is followed by 96+ zero
bytes of padding, so we simply append " androidboot.veritymode=logging".

Verification: after flashing, `adb shell getprop ro.boot.veritymode` must
return "logging".
"""
import sys

LK_IN = "/home/puffercat/sunmi-p1-experiments/dumps/lk.bin"
LK_OUT = "/home/puffercat/sunmi-p1-experiments/lk_verity_logging.img"

CMDLINE = (b"console=tty0 console=ttyMT3,921600n1 root=/dev/ram "
           b"vmalloc=496M androidboot.hardware=mt6580")

# The replacement must NOT be longer than the original: LK may copy the string
# into a fixed-size buffer, and the first attempt (which appended 31 bytes and
# made it 122 chars) did not boot.  So trade the two debug consoles - harmless
# for normal use - for the verity token, keeping the functional parts:
#   root=/dev/ram                  initramfs, required
#   vmalloc=496M                   MTK memory layout, required
#   androidboot.hardware=mt6580    -> ro.hardware, selects /fstab.mt6580
NEW_CMDLINE = (b"root=/dev/ram vmalloc=496M androidboot.hardware=mt6580 "
               b"androidboot.veritymode=logging")

# keept for reference / assertion
ADD = b" androidboot.veritymode=logging"


def main():
    data = bytearray(open(LK_IN, "rb").read())
    off = data.find(CMDLINE)
    if off < 0:
        raise SystemExit("!! cmdline string not found in %s" % LK_IN)

    end = off + len(CMDLINE)
    if data[end] != 0:
        raise SystemExit("!! cmdline string is not NUL terminated")
    if b"veritymode" in data:
        raise SystemExit("!! image already patched")

    if len(NEW_CMDLINE) > len(CMDLINE):
        raise SystemExit("!! replacement is longer than the original (%d > %d)"
                         % (len(NEW_CMDLINE), len(CMDLINE)))

    print("old cmdline     : %s (%d chars)" % (CMDLINE.decode(), len(CMDLINE)))
    print("new cmdline     : %s (%d chars)" % (NEW_CMDLINE.decode(),
                                               len(NEW_CMDLINE)))
    print("shorter by      : %d chars (no growth -> no buffer overflow)"
          % (len(CMDLINE) - len(NEW_CMDLINE)))

    # overwrite in place and zero the remainder of the old string
    data[off:off + len(CMDLINE)] = NEW_CMDLINE + b"\x00" * (len(CMDLINE)
                                                            - len(NEW_CMDLINE))
    assert data[off + len(NEW_CMDLINE)] == 0
    print("wrote           : %s (%d bytes)" % (LK_OUT, len(data)))

    # sanity: only those bytes changed
    orig = open(LK_IN, "rb").read()
    diff = [i for i in range(len(orig)) if orig[i] != data[i]]
    print("bytes changed   : %d (offsets 0x%X..0x%X)"
          % (len(diff), diff[0], diff[-1]))
    # sanity: every changed byte must be inside the old cmdline string
    assert diff, "nothing changed?"
    assert off <= diff[0] and diff[-1] < off + len(CMDLINE), \
        "changed bytes outside the cmdline: 0x%X..0x%X" % (diff[0], diff[-1])

    open(LK_OUT, "wb").write(data)
    print("wrote           : %s (%d bytes)" % (LK_OUT, len(data)))

    # sanity: only those bytes changed
    orig = open(LK_IN, "rb").read()
    diff = [i for i in range(len(orig)) if orig[i] != data[i]]
    print("bytes changed   : %d (offsets 0x%X..0x%X)"
          % (len(diff), diff[0], diff[-1]))


if __name__ == "__main__":
    main()
