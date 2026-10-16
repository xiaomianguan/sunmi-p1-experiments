# Sunmi P1 — Lockdown Analysis (from the real ROM)

> **Status (2026-10-16): accurate, and largely borne out.** Two corrections/outcomes:
> third-party installs turned out to be gated by `p1_security_trans_mode` rather than by
> `woyou.market` (see `README.md`), and `/system/build.prop` is read-only + dm-verity, so
> `ro.xc_delete_advanced_item=1` **still** hides the Developer options *menu entry* (the
> activity itself launches). Everything else here was confirmed against the live device.

Everything below was extracted from the device's own partitions
(`dumps/system.bin`, `dumps/recovery.bin`, `dumps/lk.bin`), not from documentation.

## How Sunmi implements the lockdown

### 1. Developer options are *deleted*, not just hidden

`/system/build.prop`:
```
line 244: ro.xc_delete_autorotate=1
line 245: ro.xc_delete_advanced_item=1      <-- THIS
line 246: ro.xc_remove_custom_version=1
line 247: ro.xc_text_center_support=yes
line  56: ro.xc_payment_type=1              <-- payment-device (production) mode
line  35: ro.product.locale=zh-CN           <-- forced locale
```

`/system/priv-app/Settings` is the **standard AOSP Settings**, patched so that it
reads the prop and removes the menu entry. Proof — this symbol is inside
`Settings.odex`:

```
DELETE_ADVANCEDITEM_SUPPORT
```

So flipping `ro.xc_delete_advanced_item` to `0` makes the "Advanced" /
Developer-options entry reappear. The normal AOSP machinery is still present:
`development_settings_enabled`, `Settings$LocalePickerActivity`, etc.

### 2. Third-party installs are blocked by the Sunmi App Store

Searching the whole 1.5 GB system image for the user-visible error string found it in
exactly one place:

```
FOUND in: .../SunmiAppStore_v3.2.51_release_v1.apk
  "Unauthorized application installation is not allowed."
```

and that APK's manifest says:

```
package = woyou.market
```

So **`woyou.market` is the install gatekeeper**. The AOSP `PackageInstaller` and
`Settings` are unmodified in this respect — Sunmi gates installs at the app layer.

### 3. Package names of the enforcement stack

| Directory | Package |
|---|---|
| `SunmiAppStore_v3.2.51_release_v1` | **`woyou.market`** — blocks unauthorised installs |
| `SunmiSecurityService_v2.0.30_release` | **`com.sunmi.sunmisecurityservice_v3`** — `sunmi/installer/`, `InstallAppObserver` |
| `SunmiSystemIntentIntercept_v1.1.5_release` | **`woyou.system.intent.intercept`** — intercepts Album/Browser/CallPhone/Camera/Music/SMS intents |
| `SunmiSystemAPI_v1.3.32_release` | **`woyou.system.api`** |

Note `woyou.*` — Sunmi's original internal namespace.

### 4. Other useful things found

- `/app/EngineerMode`, `/app/FactoryMode`, `/app/SecretCode`, `/app/EngineerTests`
  exist → MTK engineer mode is reachable by secret code.
- `/system/app` is full of the normal AOSP apps (Calculator, Camera, Gallery2,
  Browser, DocumentsUI, PrintSpooler …) so the ROM is not heavily stripped.
- `/etc/disableapplist.txt` is only the stock MTK disable list, **not** a Sunmi whitelist.
- No `shengfutong` / `sft` package anywhere in `/system` → the Shengfutong agent, if
  present, lives in `/data` (not dumped; userdata was skipped deliberately).

## Consequences for the plan

All three user-facing goals reduce to two edits plus one package to disable:

| Goal | Mechanism |
|---|---|
| Developer options | `ro.xc_delete_advanced_item=0` in `/system/build.prop` (+ `settings put global development_settings_enabled 1`) |
| Third-party installs | disable/remove **`woyou.market`** (+ `install_non_market_apps=1`) |
| System language | change `ro.product.locale` in `/system/build.prop`; the AOSP `LocalePickerActivity` is intact |
| (bonus) non-payment behaviour | `ro.xc_payment_type=0` |

`/system/build.prop` is on the read-only dm-verity `/system` partition, so the cleanest
route is a **Magisk module** that overlays `build.prop` — no need to modify `/system`
at all, and it survives an OTA/reflash. Alternatively remount `/system` rw once rooted.
