# Sunmi P1 (W6900) — Liberation Plan

> **Status (2026-10-16): historical — this was the plan of attack.**
> Outcomes: Phase 0/1 completed as written, and ADB *was* obtained — but **not** via the
> boot chain (Phases 2–3 are dead; see `VERITY.md`, which proves the chain is
> hardware-locked). ADB came from a `/data/property` patch over BROM, described in
> `ROM_ANALYSIS.md` §5. Current state: `README.md`; active work: `EXPLOITS.md`.

## Device facts (established)

| Item | Value |
|---|---|
| Model | SUNMI P1, model no. **W6900** |
| USB product string | `P1N` |
| USB serial | `P121184J00108` |
| SoC | **MediaTek MT6580** (4x ARM Cortex-A7 @ 1.3 GHz) — `dacode=0x6580` |
| Android | 6.0 / 6.0.1 (`MRA58K`), Sunmi Cloud OS |
| RAM / ROM | 1 GB / 8 GB |
| Display | 5.5" 1280x720 IPS |
| Keys | Power, **Volume Up**, **Volume Down**, capacitive Back/Home/Menu |
| Port | Micro-USB (OTG) |
| Provisioned by | Shengfutong (payment channel) |

## Why the usual tricks fail

1. **No ADB.** Developer options are hidden by Sunmi's payment "production mode", so no
   `adb` interface is exposed — the device only presents MTP (`0e8d:2008`).
2. **`mtk-su` / `mtk-easy-su` (bootless temp root) does NOT work on MT6580.**
   That exploit is ARMv8-only; MT6580 is 32-bit ARMv7 Cortex-A7. Confirmed "Fail" in the
   upstream tested-device table (MT6580 / MT6580M).
3. **Sunmi debug mode is a dead end.** Sunmi's own KB says enabling debug mode on a
   *payment* ("P") device is **irreversible**, permanently watermarks the screen, and
   requires a 24-hour authorization code issued by Sunmi support — i.e. it also
   permanently disqualifies the device. Not needed if we take the BROM route.
4. **Hardened preloader.** These units ship with
   `SBC enabled: True`, `SLA enabled: True`, `DAA enabled: True`, `SWJTAG enabled: True`
   and a **V3 lockstate** seccfg. Historically `mtk.py da seccfg unlock` **bricked**
   MT6737M/MT6753 units exactly like this (mtkclient issue #103, `SEJ Legacy Hardware
   seems not to be configured correctly`). **This was fixed upstream in Mar 2026**, so we
   must use a current mtkclient (we cloned `7cb40e7`, which is post-fix).

## The route that works

BROM (BootROM) mode is mask-ROM code — it cannot be disabled or patched. Sunmi's
hardening lives in the *preloader*, which BROM runs *after* it has already accepted
our payload. So: force the device into BROM, upload `mt6580_payload.bin`, and take
the flash directly. `mtkclient` supports MT6580 natively (`damode=LEGACY`,
`loader=mt6580_payload.bin`).

## Ordered plan

### Phase 0 — Access & backup (non-destructive)
1. Install the udev rule so the MTK device node is world-writable (needs sudo).
2. Get the device into **BROM mode** (`0e8d:0003`).
3. `mtk.py gettargetconfig` — read SBC/DAA/SLA state and hwcode.
4. `mtk.py printgpt` + `mtk.py rl dumps/` — **full partition dump = our safety net.**
   Nothing is written in this phase.

### Phase 1 — Understand the lockdown
5. Inspect the dump: `boot.img`, `lk.bin`, `preloader.bin`, `seccfg`, and the system
   partition to identify exactly which Sunmi/Shengfutong packages enforce:
   - app-install whitelist (the "unauthorized app installation is prohibited" wall),
   - hidden developer options,
   - locked system locale.
6. Verify the seccfg is V3 and readable, and record the original bytes.

### Phase 2 — Unlock the bootloader
7. `mtk.py da seccfg unlock` (V3 → `lock_state=3`), then reboot.
8. Verify "orange state"/unlocked LK behaviour.

### Phase 3 — Root
9. Patch `boot.img` with Magisk (version chosen for Android 6 / 32-bit armeabi-v7a).
10. `mtk.py da vbmeta 3` (disable verity/verification) — no-op on some legacy builds.
11. `mtk.py w boot boot.patched`, `mtk.py reset`.
12. Complete Magisk setup on-device.

### Phase 4 — The three user-facing goals (all trivial once rooted)
13. **Developer options**: `settings put global development_settings_enabled 1`,
    then neutralise the Sunmi flag that re-hides it.
14. **Third-party apps**: neutralise the whitelist enforcement
    (`com.sunmi.baseservice` / Security Center / `userlist.xml`), set
    `Settings.Global.INSTALL_NON_MARKET_APPS=1`, and uninstall/disable the
    Shengfutong MDM agent if present.
15. **System language**: Sunmi hides the locale picker. Re-enable it
    (`persist.sys.locale` / `setprop persist.sys.language`+`persist.sys.country`,
    plus re-exposing the Settings locale entry).

### Phase 5 — Optional
16. Flash TWRP recovery for ongoing backups.
17. Debloat the Sunmi stack; optionally install GMS.

## Magisk version choice (resolved)

- Magisk **v26.0** raised the minimum Android version to **6.0**; nothing later raised it
  further, and `armeabi-v7a` is still a supported ABI on master.
- Verified from the actual APK manifests with `tools/axml_minsdk.py`:
  - `Magisk-v31.0.apk` → `minSdkVersion=23` (Android 6.0) ✅
  - `Magisk-v27.0.apk` → `minSdkVersion=23` (Android 6.0) ✅
- Plan: try **v27.0** first (last "classic" app, most battle-tested on 32-bit Android 6),
  keep **v31.0** as a fallback. Both are pre-downloaded in `tools/`.

## Verified tooling in this workspace

```
venv/                  python venv with mtkclient's deps (pyusb, pycryptodome, capstone, unicorn, ...)
mtkclient/             bkerler/mtkclient @ 7cb40e7  (post-2026-03 seccfg/V3 unlock fix)
  mtkclient/payloads/mt6580_payload.bin    <- our chip's BROM payload
  52-mtk.rules         udev rule (needs sudo to install)
watch_usb.sh           polls lsusb, decodes MTP/preloader/BROM/fastboot states
brom_recon.sh          non-destructive: gettargetconfig + printgpt, logged to logs/
tools/Magisk-v27.0.apk, tools/Magisk-v31.0.apk
tools/axml_minsdk.py   AXML manifest reader (no aapt needed)
dumps/                 destination for the full ROM backup
```

## Why we go via BROM and not `fastboot`

The Sunmi `lk.bin` (Little Kernel) is the Android bootloader and is what would provide
`fastboot`. On payment ("P") devices it is not exposed as a user-accessible unlock flow,
and Sunmi documents no OEM-unlock path. BROM sits *below* LK in the chain of trust and is
mask-ROM, so it is the only entry point that cannot be hardened away.

## VERIFIED FINDINGS (from the live device)

### BROM is fully open — there is no hardening to defeat

```
Preloader - CPU:                MT6580()
Preloader - Target config:      0x0
Preloader -     SBC enabled:    False     <- no secure boot check
Preloader -     SLA enabled:    False     <- no serial link auth
Preloader -     DAA enabled:    False     <- no download agent auth
Preloader -     SWJTAG enabled: False
Preloader -     Root cert required: False
Preloader -     Mem read auth:  False
Preloader -     Mem write auth: False
Preloader -     Cmd 0xC8 blocked: False
```

MT6580 is a 2015-era part that predates MTK Secure Boot entirely. Compare with the
MT6737M/MT6753 logs in mtkclient issue #103, where `SBC/SLA/DAA` were all `True`.

**The previous "mtkclient doesn't work" was a session/timing artifact, not hardening.**
The MT6580 BootROM only answers the plug-in handshake during a short window after USB
enumeration, and `Port.wait_for_device()` only checks *enumeration*, not a successful
handshake. A second mtkclient process therefore sees the already-enumerated BROM,
assumes it is "connected", skips the handshake loop, and fails forever.
Fix: **exactly one mtkclient session per power cycle**, started before the plug-in.

### Hardware / build identity

| Item | Value |
|---|---|
| SoC | MT6580, hwcode `0x6580`, HW subcode `0x8a00`, HW ver `0xca00` |
| ME_ID | `9E20BBCF1878DE1D5E4A4544B5FD5A77` |
| Build | `alps/full_rlk6580_we_c_m/rlk6580_we_c_m:6.0/MRA58K/1521451936:user/test-keys` |
| Build date | 2018-03-19 |
| eMMC | `0x1d1f84200` bytes |
| Block device | `/dev/block/platform/mtk-msdc.0/11120000.msdc0/by-name/<part>` |

### GPT (read from the live device)

```
proinfo      0x00080000  0x300000      seccfg       0x1c80000  0x40000
nvram        0x0380000   0x500000      lk           0x1cc0000  0x60000
protect1     0x0880000   0xa00000      boot         0x1d20000  0x1000000
protect2     0x1280000   0xa00000      recovery     0x2d20000  0x1000000
para         0x3d20000   0x80000       logo         0x3da0000  0x800000
expdb        0x45a0000   0xa00000      frp          0x4fa0000  0x100000
nvdata       0x50a0000   0x2000000     metadata     0x70a0000  0x2760000
oemkeystore  0x9800000   0x200000      secro        0x9a00000  0x600000
keystore     0xa000000   0x800000      system       0xa800000  0x60000000
cache        0x6a800000  0x10000000    userdata     0x7a800000 0x156780000
flashinfo    0x1d0f80000 0x1000000
```

### seccfg is V3 and currently LOCKED

```
00000000: 414e 445f 5345 4343 4647 5f76 0000 0000  AND_SECCFG_v....
00000010: 4d4d 4d4d 0300 0000 6018 0000 f200 0000  MMMM....`.......
00000020: 0000 0001 0000 0000 0000 0000 ...
```

- `magic` = `0x4D4D4D4D`, `seccfg_ver` = 3, `seccfg_size` = 0x1860
- `seccfg_enc_len` = **`0x01000000` → LOCKED** (unlocked is `0x07F20000`)
- `seccfg_attr` (inside the SEJ-encrypted blob) is `ATTR_DEFAULT 0x33333333`;
  unlock sets it to `ATTR_UNLOCK 0x44444444`.

### boot.img is a standard Android boot image (Magisk-ready)

```
HEADER_VER      [0]
KERNEL_SZ       [6413946]      ZIMAGE_KERNEL
RAMDISK_SZ      [1379406]      RAMDISK_FMT [gzip]
PAGESIZE        [2048]
NAME            [B900_D1BOM_P1_V]
CMDLINE         [bootopt=64S3,32S1,32S1]
KERNEL_DTB_SZ   [48890]
AVB1_SIGNED
```

- `magiskboot` (x86_64, extracted from the Magisk APK) unpacks and repacks it fine.
- Ramdisk is a normal MTK cpio with `init`, `fstab.mt6580`, `init.rc`, `verity_key`.
- So we patch the boot image **offline on the host** — no need for the app on-device.

### LK (`lk.bin`) has the full standard MTK unlock flow

```
oem unlock / flashing unlock / flashing get_unlock_ability / unlock_erase
Unlock bootloader?   Yes (Volume UP):Unlock(may void warranty).
Unlock operation is not allowed        <- gated by the "unlock_allowed" flag
Start unlock flow / Unlock Pass...return to fastboot in 3s
[%s] sec_func_init -- fail to get lock state
dump lock_state, %x
[%s] Verifying %s / [%s]Bootimg verify failed / SECLIB_IMG_VERIFY
app/mt_boot/sec/sec_img_verify.c
```

LK gates image verification on the seccfg lock state, so unlocking seccfg makes LK skip
`SECLIB_IMG_VERIFY` — which is exactly what lets a Magisk-patched boot image boot.

### Lockdown surface visible from the ramdisk

`default.prop`:
```
ro.adb.secure=1
ro.secure=1
ro.debuggable=0
persist.sys.usb.config=mtp        <- why the device only ever presents MTP
```

`fstab.mt6580`:
```
.../by-name/system  /system  ext4  ro wait,verify       <- dm-verity ON for /system
.../by-name/userdata /data   ext4  ...,encryptable=...  <- not forceencrypt
```

No `sunmi` strings in the ramdisk → the app-whitelist / dev-options / locale lockdown
lives in `/system` (identified from `system.bin` in Phase 1).

### Phase 0 status

- ✅ udev rule installed at `/etc/udev/rules.d/52-mtk.rules`
- ✅ BROM reached; `gettargetconfig` captured
- ✅ GPT, `seccfg`, `lk`, `boot`, `recovery` and the rest dumped
- ⏳ `system.bin` (1.5 GB ext4, raw — not sparse) dumping

## CURRENT STATUS (2026-10-15, evening)

| Item | State |
|---|---|
| Full ROM + userdata backup | ✅ `dumps/` |
| BROM open, no MTK secure boot | ✅ `target_config 0x0` |
| Bootloader unlocked | ✅ `unlocked: yes` |
| `adb_enabled` / `install_non_market_apps` in `/data` | ✅ patched (2 blocks, verified) |
| **ADB actually working** | ⏳ patch built + validated, **not yet flashed** |
| Patched LK accepted by preloader | ⏳ `lk_patched_test.img` ready, untested |

**Next actions, in order:**

1. `./brom_read_live.sh` (read-only; battery pull) → confirm the live `/property`
   directory is unchanged since the snapshot.
2. `./brom_write_prop.sh` (battery pull) → writes 3 blocks; adb comes up on boot.
3. On device: tap **Allow USB debugging** → `adb devices` should show `0e8d:201d`.
4. Then, over adb: developer options, locale, `pm disable-user --user 0 woyou.market`,
   `pm install tools/Magisk-v27.0.apk`.
5. `./brom_write.sh lk lk_patched_test.img verify` → boot with Vol Up held; the menu
   reading `***LK PATCHED***:` proves a modified LK is accepted (gate on Paths A/B).
6. Path A/B/D: custom boot (verity off, de-Sunmi'd ROM) + Magisk.

See `ROM_ANALYSIS.md` §5 for why `adb_enabled=1` alone can never work on this ROM,
and why the `/data` patch is 3 in-place blocks instead of a normal file creation.

## Safety notes

- **Phase 0 is read-only.** We take a complete dump before writing anything.
- `da seccfg unlock` + wiping `userdata`/`metadata`/`md_udc` **erases all user data**.
- After unlocking, the device will show an "orange state"/unlocked warning at boot.
- Once modified, this unit can never legitimately process card payments again.
  That is fine here — it is out of support and being repurposed as a plain Android device.

