# Sunmi P1（W6900 / MTK6580 / Android 6.0.1）上的 dm-verity

> **状态（2026-10-16）：结论不变 —— 引导链已被硬件锁死。** 本文是该结论的权威记录，
> 下面的实验就是证据。请不要再重复这些实验。工作重心已转移到 `EXPLOITS.md` 中的
> 内核/用户态路线（当前状态见 `README.md`，面向 agent 的交接见 `HANDOFF.md`）。

> 本文是 `VERITY.md` 的简体中文译本。

目标：让 dm-verity 停止对 `/system` 的强制校验，从而让被修改过的 `/system`
（去 Sunmi 化的 ROM、安装到 `/system` 的 root）能够启动。这是定制 ROM 的门槛。

## 校验模式是如何决定的（AOSP 6.0.1 `fs_mgr`）

`fs_mgr_setup_verity()` -> `load_verity_state()`：

```c
property_get("ro.boot.veritymode", propbuf, "");     // (1) 内核命令行优先
if (*propbuf != '\0') {
    if (!strcmp(propbuf, "enforcing")) { *mode = VERITY_MODE_DEFAULT; return 0; }
    else if (!strcmp(propbuf, "logging")) { *mode = VERITY_MODE_LOGGING; return 0; }
}
if (get_verity_state_offset(fstab, &offset) < 0) {   // (2) 否则看 TLV 状态
    *mode = VERITY_MODE_EIO; return 0;               //     ……否则 EIO = 强制校验
}
```

`enum verity_mode`（fs_mgr/include/fs_mgr.h）：EIO=0、**LOGGING=1**、
RESTART=2、DEFAULT=RESTART。`VERITY_MODE_LOGGING` 会让
`load_verity_table()` 把 `ignore_corruption` 传给 dm-verity，即被破坏
（= 被修改）的块只记录日志，仍然照常返回数据。

## /system 的磁盘布局（用三种方式交叉验证）

```
0x00000000 .. 0x5F3DF000   ext4 文件系统   (s_blocks_count 390111 x 4096)
0x5F3DF000 .. 0x5F3E7000   verity 元数据   (32 KB；magic 0xb001b001 在 +0)
0x5F3E7000 .. 0x60000000   dm-verity 哈希树 (verity 表：hash_start_block 390119)
```

* 元数据起点 == `ext4_get_target_device_size()` == fs_size，而且尾部 magic
  确实存在于 `dumps/system.bin` 中。
* verity 表的 `hash_start_block 390119 x 4096` == 0x5F3E7000 == 元数据 + 32768，
  所以元数据块不属于哈希树。
* TLV 区域 = 元数据 + 0x4000（"跳过 cryptfs 元数据区"），magic 0x01564c54，
  标签形如 `<tag>_<mountpoint>`，以 `eod 0` 结束。

分区基址（GPT）：system 0x0A800000、userdata 0x7A800000、lk 0x001CC0000。

## 为什么 TLV 这条路在这个 ROM 上是死的

* fstab 那一行是 `/system ... ext4 ro wait,verify` —— **裸的 `verify`**。
  `verity_loc` 只会从带路径的 fstab 选项设置
  （fs_mgr_fstab.c 中 `flag_vals.verity_loc = strdup(start + 1)`），因此
  `fstab->verity_loc == NULL` -> `metadata_find(NULL,...)` -> -1 -> mode = EIO。
* Sunmi/MTK 在 `init.rc` 里把状态处理注释掉了：
  `#    verity_load_state`（第 25 行）与 `#    verity_update_state`（第 239 行）。
* 经验证实：`brom_write_verity.sh` 在写入**之前**先从设备读回了 TLV 块，结果是
  **全零** —— 说明 fs_mgr 从未写过任何状态。随后我们写入自己那份（逐字节精确的）TLV
  并读回比对完全一致，但它只会被忽略。无害；保持预置状态即可。
* `adb disable-verity` 会拒绝：`disable-verity only works for userdebug builds`
  （user 版本 → 没有编入 `ALLOW_ADBD_DISABLE_VERITY`；而且这个 init 里也不存在
  `VERITY_METADATA_MAGIC_DISABLE` 分支）。

## 真正的杠杆：内核命令行

LK 负责生成命令行，且不设置任何 verity 属性，所以 fs_mgr 会落到 EIO。
LK 的命令行字符串位于 lk.bin 的文件偏移 **0x3C63C** 处：

```
console=tty0 console=ttyMT3,921600n1 root=/dev/ram vmalloc=496M androidboot.hardware=mt6580
```

其后是 **609 个零字节的填充**，所以我们追加 31 个字节：

```
... androidboot.hardware=mt6580 androidboot.veritymode=logging
```

* `tools/lk_verity_logging_patch.py` -> `lk_verity_logging.img`
  （393216 字节，与出厂完全一致，只改了 31 个字节）。
* `./brom_write.sh lk lk_verity_logging.img verify` 负责写入并校验。
* 回滚：`./brom_write.sh lk dumps/lk.bin`。
* 这只有在 preloader 不校验 LK 时才可能成立 —— lk.bin 没有附加 MTK 签名，正是这一点的
  证据。如果设备无法启动，就通过 BROM 恢复出厂 LK。

## 验证

1. `adb shell getprop ro.boot.veritymode` -> 必须输出 **logging**
   （init 会把命令行变成 `ro.boot.*`；fs_mgr 读的正是它）。
2. 再做功能性验证：`tools/system_file_patch.py` 对 `/system` 中的文件做等长原地修改
   （长度不变，因此 inode/大小/extent 都不变），并输出需要通过 BROM 写入的 4 KB 闪存块。
   第一个真实用例：把 `/build.prop` 里的 `ro.xc_delete_advanced_item=1` 改成 `=0`
   （恢复开发者选项菜单入口），闪存地址 0x291F6000，块号 125430。

## 结论（2026-10-16）：引导链已被硬件锁死

我们通过实验证明：这条链的每一层都校验下一层，而我们无法改动其中任何一层：

| 尝试 | 结果 |
|---|---|
| LK 命令行字符串后追加 31 字节 | 无法启动 |
| LK 命令行字符串被替换（85 字符，更短） | 无法启动 |
| LK 仅改动 16 字节的**显示字符串**（`Select Boot Mode:` -> `***LK PATCHED***:`） | **无法启动** |
| boot1（preloader）中一个纯日志字符串改了 **1 个字节**（`mtk_arch_reset at pre-loader!` -> `...?`） | **无法启动** |
| 恢复出厂 LK / 出厂 boot1 | 每次都能启动 |

所有写入都通过读回逐字节验证过，所以内容确实写进去了，只是没有被执行。preloader 中
**不存在 LK 的明文哈希**（我们对四种载荷变体计算了 sha256/sha1/md5/crc32），因此这个
校验是基于签名的，期望值在一个我们无法伪造的已签名结构里。

eMMC 的 **boot1** 区域存放 preloader，其中包含 MTK 的 seclib
（`seclib_boot.c`、`[%s] Verification Pass/Fail`、`[%s] Verifying %s`、
`[%s] invalid sboot config`），以及 `AND_SECCTRL_v` —— 它列出了要校验的镜像：
`lk, logo, boot, recovery, system, secro`。它的 SEC 配置来自 SECRO 分区，而 SECRO
本身也是签名的。

"已解锁引导加载程序"（MTK `seccfg` 标志）给我们带来的是：LK 不再拒绝 fastboot 操作。
它**并不会**让 BROM 接受未签名的 preloader，也不会让 preloader 接受被修改的 LK。
`fastboot getvar unlocked` 返回 `yes`、`secure` 返回 `no`，但 `fastboot flash boot`
仍被 LK 自己的白名单拒绝，而且任何被修改的 LK 本来也启动不了。

### 后果

* **dm-verity 无法关闭。** 模式只能来自内核命令行（由 LK 生成）或 ramdisk 里的 fstab
  （在 boot 镜像内）—— 两者都在 LK 之后，而 LK 在 preloader 之后，preloader 又在 BROM 之后。
* **没有定制 ROM，没有 Magisk 的 boot 补丁，也无法通过引导链取得 root。**
* `/data` 仍然完全可用（没有 verity，而且我们可以通过 BROM 写它），adb 就是这样拿到的。

### 仍然取得的成果（均已在真机验证）

* **adb** —— `persist.sys.usb.config=mtp,adb`，由 Android 原生地跨重启保持
  （`brom_write_verity.sh` 写了 TLV；随后是 Android 自己重写了它）
* **第三方安装** —— `Settings.Secure.install_non_market_apps` 原本是 `0`；我们最先改的
  *global* 命名空间是错的。Magisk 27.0 已安装。注意 Sunmi 的 PMS 补丁
  `SunmiUtils.allowInstall()` 仍会拦截 MoreLocale 之类的应用（"Forbid By Sunmi Server"），
  而 `ALLOW_INSTALL` 设 0 还是 1 都没有区别。
* **开发者选项** —— `com.android.settings/.DevelopmentSettings` 可以启动
  （Sunmi 只删掉了 dashboard 别名；`ro.xc_delete_advanced_item=1` 隐藏了菜单入口，
  修它需要改 /system）
* **篡改叠加层已移除** —— 它是 `p1_security_trans_mode=0` 在驱动 SystemUI 的
  `SecurityModeReceiver`；已恢复为 `1`
* **adb 无法设置 `persist.sys.*`**（SELinux 拒绝 shell），而持有
  `CHANGE_CONFIGURATION` 的应用只有 `com.android.managedprovisioning`
  （device-owner 流程，会清空 /data）和 `com.mediatek.dataprotection` ——
  所以语言目标需要 root，而被锁死的链正好不给。

### 产物 / 回滚

* `brom_write.sh lk dumps/lk.bin`            —— 恢复 LK
* `brom_write_boot1.sh --restore`            —— 从 `dumps/preloader_boot1.bin` 恢复
  preloader（脚本永不重新抓取；该脚本的第一版会重新抓取打过补丁的 boot1，从而把补丁
  "恢复"回去）
* `brom_write_verity.sh --restore`           —— 恢复（无效的）verity TLV 块
* `lk_verity_logging.img`（31 字节）、`boot1_test/preloader_boot1_test.img`（1 字节）、
  `verity_disable/blk_0x5F3E3000.bin` —— 用过的载荷，现已全部在设备上回退
* 位于 0x69BE3000 的 verity TLV 块被**保留在原处**：已证明它在这个 ROM 上被忽略
  （fstab 里的 `verify` 没有路径 -> `verity_loc == NULL`）

## 文件

* `tools/verity_disable_patch.py`   生成 TLV 块（mode=LOGGING）
* `brom_write_verity.sh`            在 0x69BE3000 写入、校验、回滚
* `tools/lk_verity_logging_patch.py` 生成打过补丁的 LK
* `tools/system_file_patch.py`      等长的 /system 文件原地修改
* `verity_disable/`、`verity_verify/`  载荷与读回捕获
