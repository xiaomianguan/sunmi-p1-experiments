# dm-verity on the Sunmi P1 (W6900 / MTK6580 / Android 6.0.1)

> **Status (2026-10-16): conclusion unchanged — the boot chain is hardware-locked.**
> This is the authoritative record of that result; the experiments below are the evidence.
> Do not repeat them. The work moved to the kernel/userspace route in `EXPLOITS.md`
> (current state: `README.md`, agent handoff: `HANDOFF.md`).

Goal: stop dm-verity enforcing on `/system`, so a modified `/system` (de-Sunmi'd
ROM, `/system`-installed root) can boot. This is the gate for the custom ROM.

## How the mode is decided (AOSP 6.0.1 `fs_mgr`)

`fs_mgr_setup_verity()` -> `load_verity_state()`:

```c
property_get("ro.boot.veritymode", propbuf, "");     // (1) kernel cmdline wins
if (*propbuf != '\0') {
    if (!strcmp(propbuf, "enforcing")) { *mode = VERITY_MODE_DEFAULT; return 0; }
    else if (!strcmp(propbuf, "logging")) { *mode = VERITY_MODE_LOGGING; return 0; }
}
if (get_verity_state_offset(fstab, &offset) < 0) {   // (2) else the TLV state
    *mode = VERITY_MODE_EIO; return 0;               //     ... or EIO = enforce
}
```

`enum verity_mode` (fs_mgr/include/fs_mgr.h): EIO=0, **LOGGING=1**,
RESTART=2, DEFAULT=RESTART. `VERITY_MODE_LOGGING` makes
`load_verity_table()` hand dm-verity `ignore_corruption`, i.e. corrupted
(= modified) blocks are logged and still returned.

## On-disk layout of /system (verified three ways)

```
0x00000000 .. 0x5F3DF000   ext4 fs         (s_blocks_count 390111 x 4096)
0x5F3DF000 .. 0x5F3E7000   verity metadata (32 KB; magic 0xb001b001 at +0)
0x5F3E7000 .. 0x60000000   dm-verity hashtree (verity table: hash_start_block 390119)
```

* metadata start == `ext4_get_target_device_size()` == fs_size, and the footer
  magic really is there in `dumps/system.bin`.
* the verity table's `hash_start_block 390119 x 4096` == 0x5F3E7000 == metadata
  + 32768, so the metadata block is not part of the hashtree.
* TLV area = metadata + 0x4000 ("skip cryptfs metadata area"), magic
  0x01564c54, tags `<tag>_<mountpoint>`, terminated by `eod 0`.

Partition base (GPT): system 0x0A800000, userdata 0x7A800000, lk 0x001CC0000.

## Why the TLV route is dead on this ROM

* the fstab line is `/system ... ext4 ro wait,verify` - **bare `verify`**.
  `verity_loc` is only set from an fstab option that carries a path
  (`flag_vals.verity_loc = strdup(start + 1)` in fs_mgr_fstab.c), so
  `fstab->verity_loc == NULL` -> `metadata_find(NULL,...)` -> -1 -> mode = EIO.
* Sunmi/MTK commented out the state handling in `init.rc`:
  `#    verity_load_state` (line 25) and `#    verity_update_state` (line 239).
* confirmed empirically: `brom_write_verity.sh` read the TLV block back from
  the device **before** writing and it was **all zeros** - fs_mgr had never
  written a state. Our own (byte-exact) TLV was then written and read back
  identical, but it will simply be ignored. Harmless; left pre-staged.
* `adb disable-verity` refuses: `disable-verity only works for userdebug builds`
  (user build -> `ALLOW_ADBD_DISABLE_VERITY` not compiled in; the
  `VERITY_METADATA_MAGIC_DISABLE` branch does not exist in this init either).

## The actual lever: the kernel cmdline

LK builds the cmdline and does not set any verity property, so fs_mgr falls
through to EIO. LK's cmdline string sits at file offset **0x3C63C** in lk.bin:

```
console=tty0 console=ttyMT3,921600n1 root=/dev/ram vmalloc=496M androidboot.hardware=mt6580
```

followed by **609 zero bytes of padding**, so we append 31 bytes:

```
... androidboot.hardware=mt6580 androidboot.veritymode=logging
```

* `tools/lk_verity_logging_patch.py` -> `lk_verity_logging.img`
  (393216 bytes, identical to stock, exactly 31 bytes changed).
* `./brom_write.sh lk lk_verity_logging.img verify` writes + verifies it.
* Rollback: `./brom_write.sh lk dumps/lk.bin`.
* This works only if the preloader does not verify LK - lk.bin has no appended
  MTK signature, which is the evidence for that. If the device fails to boot,
  restore the stock LK over BROM.

## Verification

1. `adb shell getprop ro.boot.veritymode` -> must print **logging**
   (init turns the cmdline into `ro.boot.*`; fs_mgr reads exactly that).
2. Then prove it functionally: `tools/system_file_patch.py` edits a file in
   `/system` in place (same length, so no inode/size/extent change) and emits
   the 4 KB flash block(s) to write over BROM. First real use:
   `ro.xc_delete_advanced_item=1` -> `=0` in `/build.prop` (restores the
   Developer options menu entry) at flash address 0x291F6000, block 125430.

## CONCLUSION (2026-10-16): the boot chain is hardware-locked

We proved, by experiment, that every layer of the chain verifies the next, and
that we cannot change any of them:

| attempt | result |
|---|---|
| LK with 31 bytes appended to the cmdline string | no boot |
| LK with the cmdline string replaced (85 chars, shorter) | no boot |
| LK with a 16-byte **display-string** change only (`Select Boot Mode:` -> `***LK PATCHED***:`) | **no boot** |
| boot1 (preloader) with a **1-byte** change in a plain log string (`mtk_arch_reset at pre-loader!` -> `...?`) | **no boot** |
| stock LK / stock boot1 restored | boots every time |

All writes were verified byte-for-byte by read-back, so the content was in place
and simply not executed. There is **no plain hash** of LK in the preloader,
boot1, or any security partition (checked sha256/sha1/md5/crc32 over four
payload variants), so the check is signature-based, with the expected values
inside a signed structure we cannot forge.

The eMMC **boot1** area holds the preloader, and it contains MTK's seclib
(`seclib_boot.c`, `[%s] Verification Pass/Fail`, `[%s] Verifying %s`,
`[%s] invalid sboot config`) plus `AND_SECCTRL_v`, which lists the images it
verifies: `lk, logo, boot, recovery, system, secro`. Its SEC config is read from
the SECRO partition, which is itself signed.

What "unlocked bootloader" bought us (MTK `seccfg` flag): LK stops refusing
fastboot operations. It does **not** make BROM accept an unsigned preloader, nor
the preloader accept a modified LK. `fastboot getvar unlocked` says `yes` and
`secure` says `no`, yet `fastboot flash boot` is refused by LK's own whitelist
and any modified LK fails to boot anyway.

### Consequences

* **dm-verity cannot be disabled.** The mode can only come from the kernel
  cmdline (built by LK) or the ramdisk fstab (inside the boot image) - both
  behind LK, which is behind the preloader, which is behind BROM.
* **No custom ROM, no Magisk boot patch, no root via the boot chain.**
* `/data` remains fully usable (no verity, and we can write it over BROM),
  which is how adb was obtained.

### What was still achieved (all verified on-device)

* **adb** - `persist.sys.usb.config=mtp,adb`, persisted natively by Android
  across reboots (`brom_write_verity.sh` wrote the TLV; Android then rewrote it)
* **Third-party installs** - `Settings.Secure.install_non_market_apps` was `0`;
  the *global* one we patched first was the wrong namespace. Magisk 27.0 installed.
  Note Sunmi's PMS patch `SunmiUtils.allowInstall()` still blocks apps like
  MoreLocale ("Forbid By Sunmi Server"), and `ALLOW_INSTALL` 0/1 makes no
  difference.
* **Developer options** - `com.android.settings/.DevelopmentSettings` launches
  (Sunmi removed only the dashboard alias; `ro.xc_delete_advanced_item=1` hides
  the menu entry, which needs /system to fix)
* **Tamper overlay removed** - it was `p1_security_trans_mode=0` driving
  SystemUI's `SecurityModeReceiver`; restored to `1`
* **adb cannot set `persist.sys.*`** (SELinux denies the shell), and the only
  apps holding `CHANGE_CONFIGURATION` are `com.android.managedprovisioning`
  (device-owner flow, wipes /data) and `com.mediatek.dataprotection` - so the
  language goal needs root, which the locked chain denies.

### Artifacts / rollback

* `brom_write.sh lk dumps/lk.bin`            - restore LK
* `brom_write_boot1.sh --restore`            - restore the preloader from
  `dumps/preloader_boot1.bin` (never re-captures; the first version of that
  script re-captured the patched boot1 and "restored" the patch)
* `brom_write_verity.sh --restore`           - restore the (inert) verity TLV block
* `lk_verity_logging.img` (31 bytes), `boot1_test/preloader_boot1_test.img`
  (1 byte), `verity_disable/blk_0x5F3E3000.bin` - the payloads used, all now
  reverted on the device
* the verity TLV block at 0x69BE3000 was **left in place**: it is provably
  ignored on this ROM (fstab `verify` has no path -> `verity_loc == NULL`)

## Files

* `tools/verity_disable_patch.py`   builds the TLV block (mode=LOGGING)
* `brom_write_verity.sh`            writes it at 0x69BE3000, verifies, rollback
* `tools/lk_verity_logging_patch.py` builds the patched LK
* `tools/system_file_patch.py`      same-length in-place /system file edits
* `verity_disable/`, `verity_verify/`  payloads and read-back captures
