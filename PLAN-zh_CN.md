# Sunmi P1（W6900）—— 解放计划

> **状态（2026-10-16）：历史文档 —— 这是当初的作战计划。**
> 结果：Phase 0/1 按原样完成，而且 ADB *确实*拿到了 —— 但**不是**通过引导链
> （Phase 2–3 已死；见 `VERITY.md`，它证明了引导链被硬件锁死）。ADB 来自通过 BROM
> 打的 `/data/property` 补丁，详见 `ROM_ANALYSIS.md` §5。当前状态见 `README.md`；
> 正在进行的工作见 `EXPLOITS.md`。

> 本文是 `PLAN.md` 的简体中文译本。

## 设备事实（已确认）

| 项目 | 值 |
|---|---|
| 型号 | SUNMI P1，型号号 **W6900** |
| USB product 字符串 | `P1N` |
| USB 序列号 | `P121184J00108` |
| SoC | **MediaTek MT6580**（4x ARM Cortex-A7 @ 1.3 GHz）—— `dacode=0x6580` |
| Android | 6.0 / 6.0.1（`MRA58K`），Sunmi Cloud OS |
| RAM / ROM | 1 GB / 8 GB |
| 屏幕 | 5.5" 1280x720 IPS |
| 按键 | 电源、**音量加**、**音量减**、电容式返回/主页/菜单 |
| 接口 | Micro-USB（支持 OTG） |
| 开通方 | 盛付通（支付通道） |

## 为什么常规套路都不管用

1. **没有 ADB。** 开发者选项被 Sunmi 的支付"量产模式"隐藏，所以不暴露 `adb` 接口 ——
   设备只呈现 MTP（`0e8d:2008`）。
2. **`mtk-su` / `mtk-easy-su`（免引导临时 root）在 MT6580 上无效。**
   那个漏洞只适用于 ARMv8；MT6580 是 32 位 ARMv7 Cortex-A7。上游的"已测试设备"表中
   对 MT6580 / MT6580M 明确标注为 "Fail"。
3. **Sunmi 调试模式是死路。** Sunmi 自己的知识库说，在*支付*（"P"）设备上开启调试模式是
   **不可逆**的，会永久给屏幕打水印，并且需要 Sunmi 支持签发的 24 小时授权码 ——
   也就是说它同时也永久废掉了这台设备。走 BROM 路线就不需要它。
4. **加固的 preloader。** 这些机器出厂时
   `SBC enabled: True`、`SLA enabled: True`、`DAA enabled: True`、`SWJTAG enabled: True`，
   以及 **V3 lockstate** 的 seccfg。历史上 `mtk.py da seccfg unlock` **变砖过**
   与这些完全相同的 MT6737M/MT6753 机器（mtkclient issue #103，`SEJ Legacy Hardware
   seems not to be configured correctly`）。**这个问题已于 2026 年 3 月在上游修复**，
   所以我们必须用较新的 mtkclient（我们克隆的是 `7cb40e7`，在修复之后）。

## 可行的路线

BROM（BootROM）模式是掩膜 ROM 代码 —— 无法禁用或打补丁。Sunmi 的加固位于 *preloader*，
而 BROM 是在已经接受我们的载荷*之后*才去运行 preloader。所以：把设备强制进 BROM，
上传 `mt6580_payload.bin`，然后直接接管闪存。`mtkclient` 原生支持 MT6580
（`damode=LEGACY`、`loader=mt6580_payload.bin`）。

## 分阶段计划

### Phase 0 —— 访问与备份（非破坏性）
1. 安装 udev 规则，让 MTK 设备节点全局可写（需要 sudo）。
2. 让设备进入 **BROM 模式**（`0e8d:0003`）。
3. `mtk.py gettargetconfig` —— 读取 SBC/DAA/SLA 状态和 hwcode。
4. `mtk.py printgpt` + `mtk.py rl dumps/` —— **完整分区导出 = 我们的安全网。**
   本阶段不写入任何东西。

### Phase 1 —— 弄清锁机机制
5. 检查导出的内容：`boot.img`、`lk.bin`、`preloader.bin`、`seccfg` 以及 system 分区，
   精确定位到底是哪些 Sunmi/盛付通 包在实施以下管控：
   - 应用安装白名单（那道"禁止安装未授权应用"的墙），
   - 被隐藏的开发者选项，
   - 被锁定的系统语言。
6. 确认 seccfg 是 V3 且可读，并记录原始字节。

### Phase 2 —— 解锁引导加载程序
7. `mtk.py da seccfg unlock`（V3 → `lock_state=3`），然后重启。
8. 验证 "orange state"/已解锁的 LK 行为。

### Phase 3 —— Root
9. 用 Magisk 给 `boot.img` 打补丁（版本按 Android 6 / 32 位 armeabi-v7a 选择）。
10. `mtk.py da vbmeta 3`（关闭 verity/verification）—— 在某些老版本上是空操作。
11. `mtk.py w boot boot.patched`、`mtk.py reset`。
12. 在设备上完成 Magisk 设置。

### Phase 4 —— 三条面向用户的目标（一旦有 root 都很简单）
13. **开发者选项**：`settings put global development_settings_enabled 1`，
    然后中和掉 Sunmi 那个会把它重新隐藏的标志位。
14. **第三方应用**：中和白名单管控
    （`com.sunmi.baseservice` / 安全中心 / `userlist.xml`），设置
    `Settings.Global.INSTALL_NON_MARKET_APPS=1`，并卸载/禁用盛付通 MDM 代理（如果存在）。
15. **系统语言**：Sunmi 隐藏了语言选择器。重新启用它
    （`persist.sys.locale` / `setprop persist.sys.language`+`persist.sys.country`，
    并重新暴露 Settings 里的语言入口）。

### Phase 5 —— 可选
16. 刷入 TWRP recovery 以便持续备份。
17. 精简 Sunmi 组件；可选安装 GMS。

## Magisk 版本选择（已确定）

- Magisk **v26.0** 把最低 Android 版本提到了 **6.0**；之后的版本没有再提高，而且
  `armeabi-v7a` 在主线上仍是受支持的 ABI。
- 用 `tools/axml_minsdk.py` 从实际的 APK 清单中验证：
  - `Magisk-v31.0.apk` → `minSdkVersion=23`（Android 6.0）✅
  - `Magisk-v27.0.apk` → `minSdkVersion=23`（Android 6.0）✅
- 计划：先试 **v27.0**（最后一个"经典"版本，在 32 位 Android 6 上久经考验），
  保留 **v31.0** 作为备选。两者都已预下载在 `tools/`。

## 本工作区中已验证的工具

```
venv/                  python venv，含 mtkclient 的依赖（pyusb、pycryptodome、capstone、unicorn……）
mtkclient/             bkerler/mtkclient @ 7cb40e7（含 2026-03 之后的 seccfg/V3 解锁修复）
  mtkclient/payloads/mt6580_payload.bin    <- 本芯片的 BROM 载荷
  52-mtk.rules         udev 规则（安装需要 sudo）
watch_usb.sh           轮询 lsusb，解析 MTP/preloader/BROM/fastboot 状态
brom_recon.sh          非破坏性：gettargetconfig + printgpt，日志写入 logs/
tools/Magisk-v27.0.apk, tools/Magisk-v31.0.apk
tools/axml_minsdk.py   AXML 清单读取器（不需要 aapt）
dumps/                 完整 ROM 备份的目标目录
```

## 为什么走 BROM 而不是 `fastboot`

Sunmi 的 `lk.bin`（Little Kernel）就是 Android 引导加载程序，也是提供 `fastboot` 的组件。
在支付（"P"）设备上它不暴露为用户可用的解锁流程，Sunmi 也没有公开任何 OEM 解锁途径。
BROM 在信任链中位于 LK *之下*，而且是掩膜 ROM，所以它是唯一无法被加固掉的入口。

## 已验证的发现（来自真机）

### BROM 完全开放 —— 没有任何加固需要击败

```
Preloader - CPU:                MT6580()
Preloader - Target config:      0x0
Preloader -     SBC enabled:    False     <- 没有安全启动校验
Preloader -     SLA enabled:    False     <- 没有串行链路认证
Preloader -     DAA enabled:    False     <- 没有下载代理认证
Preloader -     SWJTAG enabled: False
Preloader -     Root cert required: False
Preloader -     Mem read auth:  False
Preloader -     Mem write auth: False
Preloader -     Cmd 0xC8 blocked: False
```

MT6580 是 2015 年的芯片，早于 MTK Secure Boot 的整个体系。对比 mtkclient issue #103 里
MT6737M/MT6753 的日志，那些机器的 `SBC/SLA/DAA` 全都是 `True`。

**之前所谓"mtkclient 不工作"是会话/时序问题，不是加固。**
MT6580 的 BootROM 只在 USB 枚举后的一小段时间窗口内应答插入握手，而
`Port.wait_for_device()` 只检查*枚举*，不检查握手是否成功。因此第二个 mtkclient 进程会看到
已经枚举过的 BROM，误以为"已连接"，跳过握手循环，然后永远失败。
解决办法：**每次上电只跑一个 mtkclient 会话**，并且要在插线之前就启动它。

### 硬件 / 构建标识

| 项目 | 值 |
|---|---|
| SoC | MT6580，hwcode `0x6580`，HW subcode `0x8a00`，HW ver `0xca00` |
| ME_ID | `9E20BBCF1878DE1D5E4A4544B5FD5A77` |
| 构建 | `alps/full_rlk6580_we_c_m/rlk6580_we_c_m:6.0/MRA58K/1521451936:user/test-keys` |
| 构建日期 | 2018-03-19 |
| eMMC | `0x1d1f84200` 字节 |
| 块设备 | `/dev/block/platform/mtk-msdc.0/11120000.msdc0/by-name/<part>` |

### GPT（从真机读取）

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

### seccfg 是 V3，且当前处于 LOCKED

```
00000000: 414e 445f 5345 4343 4647 5f76 0000 0000  AND_SECCFG_v....
00000010: 4d4d 4d4d 0300 0000 6018 0000 f200 0000  MMMM....`.......
00000020: 0000 0001 0000 0000 0000 0000 ...
```

- `magic` = `0x4D4D4D4D`、`seccfg_ver` = 3、`seccfg_size` = 0x1860
- `seccfg_enc_len` = **`0x01000000` → LOCKED**（已解锁是 `0x07F20000`）
- `seccfg_attr`（位于 SEJ 加密块内部）是 `ATTR_DEFAULT 0x33333333`；
  解锁会把它设为 `ATTR_UNLOCK 0x44444444`。

### boot.img 是标准 Android boot 镜像（Magisk 就绪）

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

- `magiskboot`（x86_64，从 Magisk APK 中提取）可以正常解包和重打包。
- Ramdisk 是常规的 MTK cpio，含 `init`、`fstab.mt6580`、`init.rc`、`verity_key`。
- 所以我们在**主机上离线**给 boot 镜像打补丁 —— 不需要设备上的 App。

### LK（`lk.bin`）包含完整的标准 MTK 解锁流程

```
oem unlock / flashing unlock / flashing get_unlock_ability / unlock_erase
Unlock bootloader?   Yes (Volume UP):Unlock(may void warranty).
Unlock operation is not allowed        <- 受 "unlock_allowed" 标志限制
Start unlock flow / Unlock Pass...return to fastboot in 3s
[%s] sec_func_init -- fail to get lock state
dump lock_state, %x
[%s] Verifying %s / [%s]Bootimg verify failed / SECLIB_IMG_VERIFY
app/mt_boot/sec/sec_img_verify.c
```

LK 依据 seccfg 的锁定状态来决定是否做镜像校验，所以解锁 seccfg 会让 LK 跳过
`SECLIB_IMG_VERIFY` —— 这正是让打过 Magisk 补丁的 boot 镜像能启动的原因。

### 从 ramdisk 可见的锁机面

`default.prop`：
```
ro.adb.secure=1
ro.secure=1
ro.debuggable=0
persist.sys.usb.config=mtp        <- 设备为什么永远只呈现 MTP
```

`fstab.mt6580`：
```
.../by-name/system  /system  ext4  ro wait,verify       <- /system 的 dm-verity 是开着的
.../by-name/userdata /data   ext4  ...,encryptable=...  <- 不是 forceencrypt
```

ramdisk 里没有任何 `sunmi` 字符串 → 应用白名单 / 开发者选项 / 语言 的锁机逻辑都在
`/system` 里（在 Phase 1 中从 `system.bin` 定位）。

### Phase 0 状态

- ✅ udev 规则已安装到 `/etc/udev/rules.d/52-mtk.rules`
- ✅ 已进入 BROM；已捕获 `gettargetconfig`
- ✅ GPT、`seccfg`、`lk`、`boot`、`recovery` 及其余分区已导出
- ⏳ `system.bin`（1.5 GB ext4，raw 而非 sparse）正在导出

## 当时的状态（2026-10-15 傍晚）

> 下面是**历史快照**。它已被后续结果取代：adb 已通过 `/data/property` 补丁获得，
> 而引导链路线（Patched LK 等）已被证明不可行。见 `VERITY.md` 与 `README.md`。

| 项目 | 状态 |
|---|---|
| 完整 ROM + userdata 备份 | ✅ `dumps/` |
| BROM 开放，无 MTK 安全启动 | ✅ `target_config 0x0` |
| 引导加载程序已解锁 | ✅ `unlocked: yes` |
| `/data` 中的 `adb_enabled` / `install_non_market_apps` | ✅ 已打补丁（2 个块，已验证） |
| **ADB 真正可用** | ⏳ 补丁已构建并验证，**尚未刷入** |
| preloader 接受打过补丁的 LK | ⏳ `lk_patched_test.img` 已就绪，未测试 |

**接下来的动作（按顺序）：**

1. `./brom_read_live.sh`（只读；需拔电池）→ 确认实机 `/property` 目录与快照一致。
2. `./brom_write_prop.sh`（需拔电池）→ 写 3 个块；开机后 adb 就会起来。
3. 在设备上点 **允许 USB 调试** → `adb devices` 应显示 `0e8d:201d`。
4. 然后通过 adb：开发者选项、语言、`pm disable-user --user 0 woyou.market`、
   `pm install tools/Magisk-v27.0.apk`。
5. `./brom_write.sh lk lk_patched_test.img verify` → 按住音量加开机；菜单显示
   `***LK PATCHED***:` 即可证明被修改的 LK 会被接受（Path A/B 的门槛）。
6. Path A/B/D：定制 boot（关闭 verity、去 Sunmi 化的 ROM）+ Magisk。

关于为什么单独设 `adb_enabled=1` 在这个 ROM 上永远不可能生效，以及为什么 `/data` 补丁是
3 个原地修改的块而不是正常创建文件，见 `ROM_ANALYSIS.md` §5。

## 安全注意事项

- **Phase 0 是只读的。** 在写入任何东西之前，我们先做完整导出。
- `da seccfg unlock` 加上擦除 `userdata`/`metadata`/`md_udc` **会清空所有用户数据**。
- 解锁后，设备开机时会显示 "orange state"/已解锁警告。
- 一旦被修改，这台机器就永远无法再合法地处理银行卡支付。
  在这里这没关系 —— 它已过保，正被改造成一台普通 Android 设备。
