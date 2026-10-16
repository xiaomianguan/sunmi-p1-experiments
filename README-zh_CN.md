# Sunmi P1（W6900）—— 解放与 root 研究

> 本文是 `README.md` 的简体中文译本。

本工作区用证据记录了一次尝试：把一台**被严格锁定的 Sunmi P1 支付终端**
（MediaTek MT6580，Android 6.0.1）变成一台普通的 Android 设备 —— 可用的 ADB、可安装第三方应用、
开发者选项、可切换的系统语言，以及 —— 目前仍未达成的目标 —— **root**。

这里的一切都对照设备自身的分区或真机验证过。失败与成功被同等认真地记录下来，
因为其中若干失败本身就是*证明*（见 `VERITY.md`）。

## 两条路线

| 路线 | 目标 | 状态 |
|---|---|---|
| **引导链** | 解锁 → 定制 boot → Magisk → 关闭 dm-verity → 去 Sunmi 化的 ROM | ❌ **已证明被硬件锁死** |
| **内核 / 用户态** | 通过内核漏洞从非特权进程取得 root | 🔶 **进行中**（CVE-2019-2215） |

## 目前可用的能力（均在真机验证）

| 能力 | 做法 | 证据 |
|---|---|---|
| **ADB，跨重启保持** | `persist.sys.usb.config=mtp,adb`，通过 BROM 写进 `/data` | `adb devices` → `P121184J00108` |
| **任意第三方安装** | `settings put global p1_security_trans_mode 0` 关闭 Sunmi 的安装闸门 | `adb install` 成功；设为 `1` 时 PMS 返回 `Forbid By Sunmi Server` |
| **开发者选项 Activity** | `settings put global development_settings_enabled 1`，然后 `am start -n com.android.settings/.DevelopmentSettings` | 读回为 `1` |
| **无篡改叠加层** | `p1_security_trans_mode` 已恢复为 `1`（量产模式） | 读回为 `1` |
| **以 `shell` 和以应用身份执行 ARM32 代码** | 静态 musl ARM32 二进制推到 `/data/local/tmp` | `ARM32-EXEC-OK uid=2000` |
| **内核符号与偏移** | 对 `./kernel` 使用 `vmlinux-to-elf` | 50,250 个符号，基址 `c0008000`，无 KASLR |

## 做不到的事（已证明，附证据）

* **真正解锁引导加载程序。** MTK `seccfg` 显示已解锁，`fastboot` 也这么说
  （`unlocked: yes`、`secure: no`），但 preloader 校验 LK，LK 又用同时烧在两者里的
  RSA-2048 公钥校验 boot/recovery。五个修改过的镜像 —— 其中包括把一个纯日志字符串改了
  **1 个字节** —— 全部无法启动；出厂镜像每次都能启动。
* **关闭 dm-verity。** 校验模式只能来自内核命令行（由 LK 生成）或 ramdisk 里的 fstab
  （在 boot.img 内），两者都在 LK 之后。`ro.boot.veritymode` 为空，所以 `fs_mgr` 落到
  `VERITY_MODE_EIO` = 强制校验。
* **`mtk-su` / `CVE-2020-0069`** —— 只适用于 ARMv8，而且所有 MTK 驱动节点对 `shell`
  都被 SELinux 拒绝。
* **系统语言** —— 需要 `CHANGE_CONFIGURATION`，只有两个系统应用持有。
* **开发者选项的*菜单入口*** —— 被 `/system/build.prop` 里的
  `ro.xc_delete_advanced_item=1` 隐藏；`/system` 是只读 + verity，所以这需要 root。

## 设备

| 项目 | 值 |
|---|---|
| 型号 | SUNMI P1，型号号 **W6900**（USB product 字符串 `P1N`） |
| SoC | **MediaTek MT6580** —— 4x Cortex-A7，armv7l，`hwcode 0x6580` |
| 系统 | Android 6.0.1（`MRA58K`），内核 **3.18.19**，Sunmi Cloud OS |
| 构建 | `alps/full_rlk6580_we_c_m/...:6.0/MRA58K/1521451936:user/test-keys`（2018-03-19） |
| 安全补丁级别 | **2017-08-05**（约两年未打补丁） |
| SELinux | Enforcing |
| 存储 | eMMC 8 GB；分区 `system 0x60000000`、`userdata 0x156780000`、`lk 0x60000` |
| 锁机方式 | Sunmi 支付/"量产"模式：无 ADB、禁止第三方安装、无开发者选项、强制语言 |

## 文档

| 文件 | 内容 |
|---|---|
| **`README.md`** | 本文件 —— 概览、状态、如何运行各项脚本 |
| **`HANDOFF.md`** | **面向 agent** 的交接说明：精确状态、待办项、下一步（不提供中文版） |
| `PLAN.md` | 最初的解放计划、设备事实、GPT、seccfg、已验证的工具链 |
| `ROM_ANALYSIS.md` | 信任模型（BROM → preloader → LK → boot）、通往开放引导加载程序的各条路径，以及卡住 ADB 的 `persist.sys.usb.config` 死锁 |
| `VERITY.md` | dm-verity 分析，**以及引导链被硬件锁死的证明**；仍然取得的成果 |
| `EXPLOITS.md` | 用户态/内核攻击面，以及 CVE-2019-2215 binder UAF 的工作记录（Update 1–6） |
| `analysis/FINDINGS_LOCKDOWN.md` | Sunmi 如何实现锁机，来自真实 ROM（哪个包负责哪项管控） |

每一份面向人类的文档都提供了简体中文译本，文件名为 `*-zh_CN.md`
（`README-zh_CN.md`、`PLAN-zh_CN.md`、`ROM_ANALYSIS-zh_CN.md`、`VERITY-zh_CN.md`、
`EXPLOITS-zh_CN.md`、`analysis/FINDINGS_LOCKDOWN-zh_CN.md`）。
`HANDOFF.md` 刻意**不**提供译本 —— 它是写给接手工作的 AI agent 的，而不是给人看的。

## 环境准备

```sh
# 1. udev 规则，让 MTK 设备节点全局可写（只需要一次的 sudo）
sudo cp 52-mtk.rules /etc/udev/rules.d/ && sudo udevadm control --reload

# 2. python venv，含 mtkclient 的依赖（pyusb、pycryptodome、capstone、unicorn）
#    已经内置好；所有 BROM 脚本都调用 ./venv/bin/python

# 3. mtkclient 已内置：bkerler/mtkclient @ 7cb40e7，即 2026-03 之后的
#    seccfg/V3 解锁修复版本。更早的版本会变砖 MT6737M/MT6753 一类的机器。
```

## 运行 BROM 脚本 —— 必须遵守的规则

1. **每次上电只跑一个 mtkclient 会话。** MT6580 的 BootROM 只在 USB 枚举后的一小段时间窗口内
   应答插入握手。第二个进程会看到已经枚举过的 BROM，误以为"已连接"，跳过握手循环，
   然后永远失败。如果会话失败，请断电重来。
2. **启动前先拔掉 USB。** 脚本会提示这一点；设备必须在脚本已经等待*之后*才插上。
3. **先只读。** `brom_recon.sh` 和 `brom_read_live.sh` 不写任何东西。
4. **每个破坏性步骤都有记录在案的回滚方式**（见下表）。
5. 所有会话日志写入 `logs/`。

### 导出 / 读取（非破坏性）

| 脚本 | 作用 |
|---|---|
| `brom_recon.sh` | `gettargetconfig` + `printgpt`：SBC/SLA/DAA 状态与分区表 |
| `brom_dump.sh` | 完整分区导出到 `dumps/` —— 安全网 |
| `brom_dump_userdata.sh` | 导出 `/data`（很大；属性补丁用到了它） |
| `brom_read_live.sh` | 读取实机的 `/property` 与 `settings_global.xml` 块，便于在写入前对比补丁 |
| `brom_read_back.sh` | 写入后读回某段区域以校验 |
| `brom_diag_restore.sh` | 从 `dumps/` 快照恢复 |

### 写入（破坏性 —— 请先看回滚列）

| 脚本 | 写入什么 | 回滚 |
|---|---|---|
| `brom_write.sh <part> <file> [verify]` | 从文件写入任意分区 | 用 `dumps/` 中的原始数据重写 |
| `brom_write_prop.sh` | 启用 ADB 的 3 块 `/data/property` 补丁 | `--restore` |
| `brom_write_prop_live.sh` | 同上，针对实机布局 | `--restore` |
| `brom_write_settings.sh` | `settings_global.xml` 块（`adb_enabled`、`install_non_market_apps`） | 恢复已捕获的块 |
| `brom_write_verity.sh` | （无效的）dm-verity TLV 块 | `--restore` |
| `brom_write_boot1.sh` | eMMC boot1 区域中的 preloader | `--restore`（来自 `dumps/preloader_boot1.bin`） |
| `brom_flash_boot.sh` | `boot` / `recovery` 镜像 | `./brom_write.sh boot dumps/boot.bin` |
| `brom_unlock.sh`、`brom_unlock_try2.sh` | MTK `seccfg` 解锁（**会清空 userdata**） | `brom_write.sh seccfg dumps/seccfg.bin` |
| `brom_recover.sh` | 写入失败后的恢复路径 | — |
| `host_patch.sh`、`do_restore.sh` | 主机侧的镜像打补丁 / 恢复辅助脚本 | — |

### fastboot / 监控 / 分析

| 脚本 | 作用 |
|---|---|
| `fastboot_recon.sh`、`fastboot_frp_probe.sh` | 探测 LK fastboot 状态与 FRP |
| `watch_usb.sh`、`monitor_usb.sh` | 轮询 `lsusb`，解析 MTP / preloader / BROM / fastboot 状态 |
| `monitor_read.sh`、`wait_and_analyze.sh` | 观察一次读/写会话 |
| `build_adb_boot.sh` | 构建启用 ADB 的 boot 镜像 |
| `analyze_system.sh`、`analyze_userdata.sh` | 对导出的镜像做离线分析 |
| `post_root.sh` | root 之后的步骤（在有 root 之前是阻塞的） |

## 工具

| 工具 | 用途 |
|---|---|
| `tools/x.c` | **当前的 CVE-2019-2215 利用程序**（干净、自包含、可编译）。用法：`x w <segs> <addr> <value>`、`x leak <segs>`，直接 `x` 则跑完整链条 |
| `tools/sunmi2215.c` | 早先的版本 —— 多次修补后已不连贯，仅供参考 |
| `tools/poc_qu1ckr00t.c`、`tools/poc_dimitri.c` | 作为参考的公开 PoC（arm64 / 其他内核） |
| `tools/rootshell.sh` | 由 `core_pattern` 执行的 root 助手：运行 `/data/local/tmp/.rcmd` 中的命令，日志写到 `.rout` |
| `tools/make_property_patch.py` | 构建 3 块 `/data/property` 补丁（硬链接技巧；不触碰分配器元数据） |
| `tools/verity_disable_patch.py`、`tools/lk_verity_logging_patch.py` | dm-verity TLV 与 LK 命令行载荷构建器 |
| `tools/system_file_patch.py`、`tools/ext4_patch.py` | 等长的 `/system` 与 ext4 原地修改 |
| `tools/exported_components.py` | 清单攻击面列举器（导出组件 + 守卫权限） |
| `tools/axml_minsdk.py` | 读取 APK 清单中的 `minSdkVersion`，无需 `aapt` |
| `tools/check_live.py`、`diff_extract.py`、`lk_base.py`、`mtk_sig_check.py`、`locale_pick.py`、`find_trust_anchor.py` | 各种分析辅助脚本 |

## 编译并运行利用程序

```sh
TC=toolchain/arm-linux-musleabi-cross/bin/arm-linux-musleabi-gcc
$TC -static -O2 -o /tmp/x tools/x.c

P=cc.wuersan008.smprint
adb push /tmp/x /sdcard/x
adb shell "run-as $P cp /sdcard/x /data/data/$P/x; run-as $P chmod 700 /data/data/$P/x"
adb shell "run-as $P /data/data/$P/x w 32 0xc0cd0de0 0x214e5750"   # 单次写入尝试
```

它必须在**应用**域中运行（`run-as`），而不是 `shell`，并且要从 `/data/data/<pkg>/` 下运行。
运行期间发生内核 panic 会需要一次重启。

## 仓库结构

```
kernel、kernel_dtb、ramdisk.cpio   从 boot.img 提取（逆向 / 利用目标）
dumps/                             完整设备备份（约 18 GB）+ 打过补丁的载荷
analysis/                          从导出内容中提炼的结论
logs/                              每一次脚本化 BROM / adb 会话的日志
sunmiapps/                         为做分析而提取的 Sunmi 系统 APK
wowrites*/                         各次实验的临时目录
verity_*/ boot1_*/ prop_verify*/   补丁载荷与读回捕获
*.img                              引导链实验用的已打补丁 boot/LK 镜像
tools/                             利用程序源码、PoC、主机侧补丁构建器
mtkclient/ venv/ toolchain/        内置的上游代码与工具链（已被 gitignore）
```

## 不在本仓库中的东西

**`SunmiPrint/`** —— 用作 `untrusted_app` 测试载体的打印机测试应用
（`cc.wuersan008.smprint`）。它是一个**独立项目，有自己独立的仓库**，已在 `.gitignore`
中列出，本工作区中没有任何内容把它当作位于此处。`EXPLOITS.md` 中提到
`cc.wuersan008.smprint` 时，指的是**安装在设备上**的那个应用，而不是本目录树中的路径。

## 注意事项

* 这是一台**支付终端**。一旦被修改，它就永远无法再合法地处理银行卡支付。
  它已过保，正被改造成一台普通 Android 设备。
* `seccfg` 解锁**会清空所有用户数据**。
* 在排查错过重分配（miss）时，利用程序会故意让内核 panic。panic 之后 adb *服务端*会变成
  陈旧状态：在断定设备坏了之前，先执行 `adb kill-server && adb start-server`。
  P1 以 `0e8d:201d` / `"P1N"`、接口 `ff/42/01` 出现，是它的**正常已启动**状态，
  而不是 preloader 模式。
* 请保留 `dumps/`。它是唯一的回头路。
