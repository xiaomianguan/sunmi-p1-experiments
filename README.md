# Sunmi P1 (W6900) — liberation & root research

This workspace documents, with evidence, the attempt to turn a **locked-down Sunmi P1
payment terminal** (MediaTek MT6580, Android 6.0.1) into an ordinary Android device:
working ADB, third-party app installs, developer options, a changeable system language,
and — the goal still open — **root**.

Everything here was verified against the device's own partitions or on the live device.
Failures are documented as carefully as successes, because several of them are *proofs*
(see `VERITY.md`).

## Two tracks

| Track | Goal | State |
|---|---|---|
| **Boot chain** | unlock → custom boot → Magisk → dm-verity off → de-Sunmi'd ROM | ❌ **proven hardware-locked** |
| **Kernel / userspace** | root via a kernel bug from an unprivileged process | 🔶 **in progress** (CVE-2019-2215) |

## What works today (verified on the live device)

| Capability | How | Evidence |
|---|---|---|
| **ADB, persistent across reboots** | `persist.sys.usb.config=mtp,adb`, patched into `/data` over BROM | `adb devices` → `P121184J00108` |
| **Arbitrary app installs** | `settings put global p1_security_trans_mode 0` disables Sunmi's install gate | `adb install` succeeds; at `1` PMS returns `Forbid By Sunmi Server` |
| **Developer options activity** | `settings put global development_settings_enabled 1`, then `am start -n com.android.settings/.DevelopmentSettings` | reads back `1` |
| **No tamper overlay** | `p1_security_trans_mode` restored to `1` (production mode) | reads back `1` |
| **ARM32 code exec as `shell` and as an app** | static musl ARM32 binaries pushed to `/data/local/tmp` | `ARM32-EXEC-OK uid=2000` |
| **Kernel symbols + offsets** | `vmlinux-to-elf` on `./kernel` | 50,250 symbols, base `c0008000`, no KASLR |

## What does *not* work (proven, with evidence)

* **Unlocking the bootloader for real.** MTK `seccfg` says unlocked and `fastboot` agrees
  (`unlocked: yes`, `secure: no`), but the preloader verifies LK and LK verifies
  boot/recovery against an RSA-2048 key baked into both. Five modified images — including
  a **1-byte** change in a plain log string — fail to boot; stock boots every time.
* **dm-verity off.** The mode can only come from the kernel cmdline (built by LK) or the
  ramdisk fstab (inside boot.img), both behind LK. `ro.boot.veritymode` is empty, so
  `fs_mgr` falls through to `VERITY_MODE_EIO` = enforce.
* **`mtk-su` / `CVE-2020-0069`** — ARMv8-only, and every MTK driver node is SELinux-denied
  to `shell` anyway.
* **System language** — needs `CHANGE_CONFIGURATION`, held only by two system apps.
* **The Developer options *menu entry*** — hidden by `ro.xc_delete_advanced_item=1` in
  `/system/build.prop`; `/system` is read-only + verity, so this needs root.

## Device

| Item | Value |
|---|---|
| Model | SUNMI P1, model no. **W6900** (USB product string `P1N`) |
| SoC | **MediaTek MT6580** — 4x Cortex-A7, armv7l, `hwcode 0x6580` |
| OS | Android 6.0.1 (`MRA58K`), kernel **3.18.19**, Sunmi Cloud OS |
| Build | `alps/full_rlk6580_we_c_m/...:6.0/MRA58K/1521451936:user/test-keys` (2018-03-19) |
| Security patch level | **2017-08-05** (~2 years of missing fixes) |
| SELinux | Enforcing |
| Storage | eMMC 8 GB; partitions `system 0x60000000`, `userdata 0x156780000`, `lk 0x60000` |
| Lockdown | Sunmi payment/"production" mode: no ADB, no 3rd-party installs, no dev options, forced locale |

## Documentation

| File | Contents |
|---|---|
| **`README.md`** | this file — overview, status, how to run everything |
| **`HANDOFF.md`** | **agent-facing** continuation note: exact state, open item, next steps (not translated) |
| `PLAN.md` | the original liberation plan, device facts, GPT, seccfg, verified tooling |
| `ROM_ANALYSIS.md` | trust model (BROM → preloader → LK → boot), paths to an open bootloader, and the `persist.sys.usb.config` deadlock that blocked ADB |
| `VERITY.md` | dm-verity analysis **and the proof that the boot chain is hardware-locked**; what still worked |
| `EXPLOITS.md` | userspace/kernel attack surface, and the CVE-2019-2215 binder UAF work log (Updates 1–6) |
| `analysis/FINDINGS_LOCKDOWN.md` | how Sunmi implements the lockdown, from the real ROM (which package blocks what) |

Simplified-Chinese translations of every human-facing doc are provided as
`*-zh_CN.md` (`README-zh_CN.md`, `PLAN-zh_CN.md`, `ROM_ANALYSIS-zh_CN.md`,
`VERITY-zh_CN.md`, `EXPLOITS-zh_CN.md`, `analysis/FINDINGS_LOCKDOWN-zh_CN.md`).
`HANDOFF.md` is deliberately **not** translated — it is written for an AI agent
picking the work up, not for a human reader.

## Setup

```sh
# 1. udev rule so the MTK device node is world-writable (needs sudo, once)
sudo cp 52-mtk.rules /etc/udev/rules.d/ && sudo udevadm control --reload

# 2. python venv with mtkclient's dependencies (pyusb, pycryptodome, capstone, unicorn)
#    already vendored — the BROM scripts call ./venv/bin/python

# 3. mtkclient is vendored: bkerler/mtkclient @ 7cb40e7, i.e. post-2026-03 seccfg/V3
#    unlock fix. Older revisions brick MT6737M/MT6753-class units.
```

## Running the BROM scripts — the rules that matter

1. **Exactly one mtkclient session per power cycle.** The MT6580 BootROM only answers the
   plug-in handshake during a short window after USB enumeration. A second process sees an
   already-enumerated BROM, assumes it is connected, skips the handshake loop, and fails
   forever. If a session fails, power-cycle and start again.
2. **Unplug USB before starting.** The scripts prompt for it; the device must be plugged in
   *after* the script is already waiting.
3. **Read-only first.** `brom_recon.sh` and `brom_read_live.sh` write nothing.
4. **Every destructive step has a documented rollback** (table below).
5. All sessions log to `logs/`.

### Dump / read (non-destructive)

| Script | What it does |
|---|---|
| `brom_recon.sh` | `gettargetconfig` + `printgpt`: SBC/SLA/DAA state and the partition table |
| `brom_dump.sh` | full partition dump into `dumps/` — the safety net |
| `brom_dump_userdata.sh` | dumps `/data` (large; used for the property patch) |
| `brom_read_live.sh` | reads the live `/property` directory block, its inode table and the candidate property data blocks, so patches are built from current state |
| `brom_read_back.sh` | reads a region back after a write, to verify |
| `brom_diag_restore.sh` | restores from the `dumps/` snapshot |

### Write (destructive — read the rollback column)

| Script | What it writes | Rollback |
|---|---|---|
| `brom_write.sh <part> <file> [verify]` | any partition from a file | re-write the original from `dumps/` |
| `brom_write_prop.sh` | the 3-block `/data/property` patch that enables ADB | `--restore` |
| `brom_write_prop_live.sh` | same, against the live layout | `--restore` |
| `brom_write_settings.sh` | `settings_global.xml` blocks (`adb_enabled`, `install_non_market_apps`) | restore the captured block |
| `brom_write_verity.sh` | the (inert) dm-verity TLV block | `--restore` |
| `brom_write_boot1.sh` | the preloader in the eMMC boot1 area | `--restore` (from `dumps/preloader_boot1.bin`) |
| `brom_flash_boot.sh` | `boot` / `recovery` images | `./brom_write.sh boot dumps/boot.bin` |
| `brom_unlock.sh`, `brom_unlock_try2.sh` | MTK `seccfg` unlock (**wipes userdata**) | `brom_write.sh seccfg dumps/seccfg.bin` |
| `brom_recover.sh` | recovery path after a failed write | — |
| `host_patch.sh`, `do_restore.sh` | host-side image patching / restore helpers | — |

### fastboot / monitoring / analysis

| Script | What it does |
|---|---|
| `fastboot_recon.sh`, `fastboot_frp_probe.sh` | probe LK fastboot state and FRP |
| `watch_usb.sh`, `monitor_usb.sh` | poll `lsusb` and decode MTP / preloader / BROM / fastboot states |
| `monitor_read.sh`, `wait_and_analyze.sh` | watch a read/write session |
| `build_adb_boot.sh` | builds the ADB-enabling boot image |
| `analyze_system.sh`, `analyze_userdata.sh` | offline analysis of the dumped images |
| `post_root.sh` | post-root steps (blocked until root exists) |

## Tools

| Tool | Purpose |
|---|---|
| `tools/x.c` | **the current CVE-2019-2215 exploit** (clean, self-contained, compiles). Modes: `x w <segs> <addr> <value>`, `x leak <segs>`, plain `x` runs the full chain |
| `tools/sunmi2215.c` | earlier exploit revision — incoherent after many patches, reference only |
| `tools/poc_qu1ckr00t.c`, `tools/poc_dimitri.c` | public PoCs used as references (arm64 / other kernels) |
| `tools/rootshell.sh` | the root helper executed by `core_pattern`: runs commands from `/data/local/tmp/.rcmd`, logs to `.rout` |
| `tools/make_property_patch.py` | builds the 3-block `/data/property` patch (hard-link trick; no allocator metadata touched) |
| `tools/fix_adb_property.py` | repairs an existing `persist.sys.usb.config` to re-enable adb — repoints the dirent at an inode we have read, fixes `i_size`, rewrites the value |
| `tools/verity_disable_patch.py`, `tools/lk_verity_logging_patch.py` | dm-verity TLV and LK cmdline payload builders |
| `tools/system_file_patch.py`, `tools/ext4_patch.py` | same-length in-place `/system` and ext4 edits |
| `tools/exported_components.py` | manifest attack-surface lister (exported components + guarding permission) |
| `tools/axml_minsdk.py` | reads `minSdkVersion` from an APK manifest without `aapt` |
| `tools/check_live.py`, `diff_extract.py`, `lk_base.py`, `mtk_sig_check.py`, `locale_pick.py`, `find_trust_anchor.py` | assorted analysis helpers |

## Building and running the exploit

```sh
TC=toolchain/arm-linux-musleabi-cross/bin/arm-linux-musleabi-gcc
$TC -static -O2 -o /tmp/x tools/x.c

P=cc.wuersan008.smprint
adb push /tmp/x /sdcard/x
adb shell "run-as $P cp /sdcard/x /data/data/$P/x; run-as $P chmod 700 /data/data/$P/x"
adb shell "run-as $P /data/data/$P/x w 32 0xc0cd0de0 0x214e5750"   # single write attempt
```

It must run in the **app** domain (`run-as`), not as `shell`, and from `/data/data/<pkg>/`.
A panic during a run costs a reboot.

## Repository layout

```
kernel, kernel_dtb, ramdisk.cpio   extracted from boot.img (RE / exploit targets)
dumps/                             full device backup (~18 GB) + patched payloads
analysis/                          findings derived from the dumps
logs/                              every scripted BROM / adb session
sunmiapps/                         Sunmi system APKs pulled for analysis
wowrites*/                         per-experiment scratch dirs
verity_*/ boot1_*/ prop_verify*/   patch payloads and read-back captures
*.img                              patched boot/LK images from the boot-chain tests
tools/                             exploit source, PoCs, host-side patch builders
mtkclient/ venv/ toolchain/        vendored upstream + toolchain (gitignored)
```

## Not in this repository

**`SunmiPrint/`** — the printer test app (`cc.wuersan008.smprint`) used as the
`untrusted_app` harness. It is a **separate project with its own repository**, is listed in
`.gitignore`, and nothing in this workspace refers to it as living here. Where
`EXPLOITS.md` mentions `cc.wuersan008.smprint`, it means the app **installed on the
device**, not a path in this tree.

## Re-enabling adb if it gets turned off

Toggling **USB debugging** off in Developer options makes `UsbDeviceManager` rewrite
`persist.sys.usb.config` without `,adb`, so adbd stops starting and the device enumerates as
`0e8d:2008` instead of `0e8d:201d`. The switch is greyed out on this ROM, so it cannot simply
be switched back on. Recover it over BROM:

```sh
./brom_read_live.sh                        # session 1: read the /property blocks (READ ONLY)
./venv/bin/python tools/fix_adb_property.py live wowrites_fix \
    --data-file=<live file> --data-block=<block>      # build payloads on the host
OUTDIR=wowrites_fix VERDIR=prop_verify_fix ./brom_write_prop_live.sh    # session 2: write
```

Both sessions want the usual dance: unplug, pull the battery, hold VOLUME UP and plug in to
catch BROM (`0e8d:0003`). The device must stay off between them. Rollback:
`OUTDIR=wowrites_fix VERDIR=prop_verify_fix ./brom_write_prop_live.sh --restore`.

How it works, and the two traps:

* `tools/fix_adb_property.py` points the existing `persist.sys.usb.config` dirent at an inode
  whose data block we have read, sets that inode's `i_size` to `len(value)` and writes
  `mtp,adb` into the block. Nothing is allocated — no bitmap, group descriptor or superblock
  change — so it is immune to the stale-snapshot problem.
* **The victim inode must be one nothing else writes.** The property file *shares* the
  victim's inode, so anything that rewrites the victim truncates the shared inode and
  destroys the value (this is what broke it once: the inode number in `victim.txt` had been
  re-assigned to `persist.sys.sunmi_pay_mode`, which Sunmi rewrites at boot). Inode numbers
  move whenever `/data` is re-initialised — always re-derive the victim from the live
  directory block. Once the system re-creates the victim under a new inode, the property ends
  up on a dedicated inode (`i_links 1`) and the fragility is gone.
* After the write, the first boot can still come up without adb if the filesystem had a dirty
  journal; a clean power cycle has always fixed it. `adb_enabled` is set to 1 by the framework
  itself once the property is right — it is a consequence, never a lever.

## Warnings

* This is a **payment terminal**. Once modified it can never legitimately process card
  payments again. It is out of support and is being repurposed as a plain Android device.
* The `seccfg` unlock **erases all user data**.
* The exploit work panics the kernel on purpose while a miss is being diagnosed. A panic
  leaves the adb *server* stale: run `adb kill-server && adb start-server` before assuming
  the device is broken. The P1 enumerating as `0e8d:201d` / `"P1N"` with interface
  `ff/42/01` is its **normal booted** state, not preloader mode.
* Keep `dumps/`. It is the only way back.
