# Sunmi P1 (W6900, MT6580) — Path to a Fully Open Bootloader / Custom ROM

> **Status (2026-10-16): historical analysis — still accurate, but the paths are all closed.**
> Paths A–E were tested and are blocked; `VERITY.md` records the proof that the boot chain
> is hardware-locked. §5 below (the `persist.sys.usb.config` deadlock) **was solved** and is
> how ADB was obtained. The effort has since moved to the kernel/userspace route in
> `EXPLOITS.md`. Current state: `README.md`.

Evidence-based analysis. Everything below was verified against the device's own
partitions, not from documentation.

## 1. The trust model, as it actually is

```
BootROM (mask ROM, unchangeable)
  └─ target_config = 0x0  ->  SBC: False, SLA: False, DAA: False
      => NO authentication at the BROM level. Full flash read/write for us.
  └─ loads PRELOADER (boot1 area)
       └─ preloader contains a HARDCODED RSA-2048 public key @ 0x1c600
       └─ lk.bin carries NO appended signature  <-- key observation
  └─ loads LK (lk partition)
       └─ LK contains the SAME hardcoded RSA-2048 public key @ 0x3c478
       └─ LK VERIFIES boot.img / recovery.img against that key
       └─ LK is linked at ~0x81E00000 (from pointer 0x81E3C26C in its rodata)
  └─ loads boot.img
       └─ signature appended after image data @ 0x76F800:
          SEQUENCE { INTEGER 1, Certificate(973B), SEQUENCE{alg, BIT STRING} }
```

### The signing certificate (from boot.img)

```
subject : C=SH, ST=ShangHai, L=ZZT, O=XCIT, OU=XCIT, CN=fym, emailAddress=766018769@qq.com
issuer  : identical  -> SELF-SIGNED
serial  : e1ba302f076819cf
valid   : 2016-11-17 .. 2016-12-17   (one month, expired)
key     : RSA 2048, sha256WithRSAEncryption
```

A self-signed cert with a personal QQ address, one month of validity, from 2016 —
a developer throwaway, not a PKI. But **it doesn't matter**, because the public key
is *baked into LK and the preloader*, so the cert is effectively decoration.

### What this means

* We **cannot** simply sign our own images — LK checks against its embedded key.
* We **can** replace that key. It's a 256-byte modulus at a known offset. That is a
  *data* edit, not a code patch: no disassembly needed, and the verification logic
  keeps working — it just starts trusting *our* key instead.
* `secure: no` (reported by LK after unlocking) is **not** the same as "verification
  off". Verification stayed on. The `secure` flag and `sec_img_verify` are independent.

### Verified blockers

| Blocker | Detail |
|---|---|
| LK verifies boot/recovery | Proven: stock image with only the signature zeroed bootloops |
| dm-verity on `/system` | Hashtree footer at `0x5f3df000` (magic `0xb001b001`), signature verified against the ramdisk's `verity_key` |
| fstab says `verify` | `/system ... ro wait,verify` inside boot.img's ramdisk |
| seccfg can't be forged | V3, hardware SEJ keyed; mtkclient's emulation is broken on MT6580 (777 failed AES blocks) |
| SECRO policy | `SDL configuration[LOCK/UNLOCK]` + `SB configuration[LOCK/UNLOCK]` records — encrypted |
| `/system` is `ro` + verity | cannot edit build.prop / remove `woyou.market` in place |

## 2. Paths to fully open — ranked

### Path A — replace the hardcoded public key in LK (RECOMMENDED)

1. Generate our own RSA-2048 keypair + self-signed cert.
2. Overwrite the 256-byte modulus at `lk.bin:0x3c478` with ours.
3. Flash the modified LK.
4. Sign our own boot/recovery images with our private key, in MTK's format.

* **Pros**: no code patching at all; the verification path is untouched and keeps
  working, just against our key. Once done, *anything* we sign boots.
* **Cons**: still need the exact signed-data format (the one open unknown — the
  signature is not over the raw image, it signs a structure).
* **Blocked only by**: whether the preloader accepts a modified LK.

### Path B — patch LK to skip `sec_img_verify`

* Find the verification call and short-circuit it (`mov r0,#0; bx lr`).
* **Pros**: deterministic; doesn't require knowing the signature format at all.
* **Cons**: needs code RE. Now much more tractable: LK base ≈ `0x81E00000`, and the
  crypto + key rodata is localised at file `0x3a000–0x3c600`, so the referencing
  code is nearby.

### Path C — patch the preloader's key as well (probably unnecessary)

* Only needed if the preloader verifies LK. Evidence says it doesn't (no LK signature).
* If it did: the preloader is verified by the BROM, which has SBC off — so the
  preloader is itself patchable.

### Path D — disable dm-verity (falls out automatically)

Once *any* of A/B works we can flash a custom boot.img that:

* removes `verify` from `fstab.mt6580`, **and**
* appends `androidboot.veritymode=disabled` to the kernel cmdline
  (current cmdline: `bootopt=64S3,32S1,32S1`).

Then `/system` mounts without dm-verity → fully editable → de-Sunmi'd ROM,
`build.prop` fixed, `woyou.market` removed, Magisk installed.

### Path E — a true custom ROM

* Kernel is **Linux 3.18.19** (MTK alps, built 2018-03-19, GCC 4.8); full `vmlinux`
  already extracted (14.5 MB).
* MTK published alps kernel sources for MT6580, so a custom **kernel** is feasible.
* But the printer / scanner / NFC / payment HALs are proprietary, and a 3.18 kernel
  cannot host modern Android.
* **Realistic ceiling**: a heavily modified *stock-derived* ROM (Android 6/7) — which
  is exactly what Paths A–D deliver. Not LineageOS 20, on this hardware, ever.

### Path F — other levers worth checking

* `mtk.py da efuse` — read the fuse state (SBC / secure boot) to confirm nothing is
  fused shut.
* Whether `fastboot flash` is permitted on a *fresh* LK instance after unlock (the
  earlier refusal came from a stale instance still holding the locked policy).
* The SECRO `SB/SDL` LOCK vs UNLOCK records — if they are the policy source and are
  decryptable, they're another lever.

## 3. The immediate decisive test

**`lk_patched_test.img`** — stock `lk.bin` with exactly one string changed:

```
"Select Boot Mode:"  ->  "***LK PATCHED***:"     (17 bytes; nothing else touched)
```

Flash it, then boot with Volume Up held. If the menu reads `***LK PATCHED***:`, the
preloader accepted and executed a modified LK, and Paths A and B are both open.
Safe: a string change can't break LK, and stock `lk.bin` restores in one write.

## 4. Recommended order

1. Finish the `/data` edit → get a shell (in progress; makes the device useful now).
2. Run the LK string test → prove a modified LK is accepted.
3. Path A: swap the LK's RSA modulus for ours (needs the signed-data format, which
   Path B's RE would also reveal).
4. Path D: flash a custom boot (verity off) → de-Sunmi the ROM + Magisk.
5. Optionally Path E: modified stock ROM / custom kernel build.

## 5. Getting a shell: the `persist.sys.usb.config` deadlock (solved)

This is *not* the usual "developer options are hidden" problem. Developer options
being hidden does not stop adb. The device has a **logic deadlock** in
`UsbDeviceManager` that makes `adb_enabled=1` alone a no-op.

### The proof

Read from real Android 6.0.1 sources (`services/usb/java/com/android/server/usb/UsbDeviceManager.java`)
and cross-checked against this ROM's own `/system/framework/oat/arm/services.odex`
(which contains `applyAdbFunction`, `removeFunction`, `addFunction`,
`persist.sys.usb.config`, `ADB_ENABLED is restricted`, `Failsafe 3` — i.e. Sunmi
did **not** strip this logic):

```java
// UsbHandler constructor
mAdbEnabled = UsbManager.containsFunction(getDefaultFunctions(), USB_FUNCTION_ADB);

private String getDefaultFunctions() {                 // reads persist.sys.usb.config
    String func = SystemProperties.get(USB_PERSISTENT_CONFIG_PROPERTY, USB_FUNCTION_NONE);
    if (USB_FUNCTION_NONE.equals(func)) func = USB_FUNCTION_MTP;
    return func;
}

// systemReady()
Settings.Global.putInt(mContentResolver, Settings.Global.ADB_ENABLED, mAdbEnabled ? 1 : 0);

private String applyAdbFunction(String functions) {
    if (mAdbEnabled) functions = UsbManager.addFunction(functions, USB_FUNCTION_ADB);
    else             functions = UsbManager.removeFunction(functions, USB_FUNCTION_ADB);
    return functions;
}
```

The loop closes like this:

1. `default.prop` in the ramdisk ships `persist.sys.usb.config=mtp` (Sunmi removed
   `,adb`), so at boot `getDefaultFunctions()` = `"mtp"`.
2. Therefore `mAdbEnabled = false`.
3. Therefore `systemReady()` **writes `adb_enabled = 0`** — silently undoing the
   `adb_enabled=1` we patched into `settings_global.xml`.
4. `setAdbEnabled()` only runs when the *setting changes*; since the framework
   itself just forced it to 0 and `mAdbEnabled` is already false, no change event
   ever fires.

So `adb_enabled` is a *consequence* of the property, not a lever. The property is
the only lever:

```
/data/property/persist.sys.usb.config = mtp,adb
```

Once that file exists, `mAdbEnabled = true` at boot, the framework itself sets
`adb_enabled = 1`, and `sys.usb.config` becomes `mtp,adb` → `init.usb.rc` starts
`adbd` and the host sees `0e8d:201d` instead of `0e8d:2008`.

### Why we do NOT create that file the obvious way

`debugfs write` would allocate an inode, a data block and a dirent, and would
therefore also rewrite the **block bitmap, inode bitmap, group descriptors and the
superblock free counts**. Our offline image is a snapshot taken while the device
was off; Android has been writing to `/data` ever since, so replaying those
allocation counters would make the allocator believe that in-use blocks are free —
i.e. it could hand them out again and corrupt live files.

### The patch we actually use: a hard link, 40 bytes, no allocator state

`/data/property` already contains property files, and ext4 directory blocks carry
a lot of slack (the last dirent's `rec_len` covers the rest of the block). So we
**append one dirent** for `persist.sys.usb.config` that points at an *existing*
inode, and give that inode our value:

| block | what | change |
|---|---|---|
| 655872 | `/property` directory block | `rec_len` 3588→28 on the last record, + new dirent `ino=163216 rec_len=3560 name_len=22 type=1` |
| 655362 | group-20 inode table, block 0 (inode 163216, offset `0xf00`) | `i_size_lo` 1→7, `i_links_count` 1→2 |
| 658946 | the linked file's data block | `"2"` → `"mtp,adb"` |

Nothing is allocated, so **not one bit of allocator metadata is touched** — no
bitmap, no group descriptor, no superblock. That makes the patch immune to the
staleness problem entirely, and it is also immune to journal replay reverting it
(a partially-reverted write degrades to "property not set", never to corruption).

The only side effect is that the linked property `persist.sys.pq.shp.idx` (a
display-sharpness index, read as an `int`) now reads `"mtp,adb"` → `0`. Nothing is
lost.

Tool: `tools/make_property_patch.py` (defaults: `--link=/property/persist.sys.pq.shp.idx`,
`--property=persist.sys.usb.config`, `--value=mtp,adb`).

### Validation performed before flashing

* `debugfs -R "cat /property/persist.sys.usb.config"` on the patched image → `mtp,adb`
* `debugfs -R "stat"` → inode 163216, size 7, links 2, same extent
* byte diff of the payloads vs the originals → 31 + 2 + 7 = 40 bytes, all accounted for
* **`e2fsck -fn` on the patched image produces byte-identical output to the
  unpatched baseline** (same single pre-existing complaint "Padding at end of inode
  bitmap is not set", same 956 inodes, same 59882 blocks) → the patch adds zero
  new filesystem findings

### Procedure (two BROM sessions, device never boots in between)

1. `./brom_read_live.sh` — read-only. Reads the 3 target blocks *plus* the two
   `settings_global.xml` blocks, so we can confirm the live `/property` directory is
   unchanged and the earlier patch is still intact. Deliberately does **not** `reset`.
2. Compare against the snapshot; only then
3. `./brom_write_prop.sh` — writes the 3 blocks, reads them back, verifies, resets.
   Rollback: `./brom_write_prop.sh --restore`.


