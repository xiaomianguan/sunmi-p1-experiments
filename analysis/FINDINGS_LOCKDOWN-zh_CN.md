# Sunmi P1 —— 锁机机制分析（来自真实 ROM）

> **状态（2026-10-16）：内容准确，且大部分已被事实验证。** 两点更正/结果：
> 第三方安装实际上由 `p1_security_trans_mode` 这个开关控制，而不是 `woyou.market`（见
> `README.md`）；并且 `/system/build.prop` 是只读 + dm-verity，因此
> `ro.xc_delete_advanced_item=1` **仍然**隐藏着"开发者选项"的*菜单入口*（该 Activity
> 本身仍可启动）。本文其余内容均已在真机上确认。

> 本文是 `analysis/FINDINGS_LOCKDOWN.md` 的简体中文译本。

以下所有内容都是从设备自身的分区中提取出来的（`dumps/system.bin`、
`dumps/recovery.bin`、`dumps/lk.bin`），并非来自任何文档。

## Sunmi 是如何实现锁机的

### 1. 开发者选项是被*删除*的，而不只是隐藏

`/system/build.prop`：
```
第 244 行: ro.xc_delete_autorotate=1
第 245 行: ro.xc_delete_advanced_item=1      <-- 就是这一行
第 246 行: ro.xc_remove_custom_version=1
第 247 行: ro.xc_text_center_support=yes
第  56 行: ro.xc_payment_type=1              <-- 支付设备（量产）模式
第  35 行: ro.product.locale=zh-CN           <-- 强制语言区域
```

`/system/priv-app/Settings` 是**标准 AOSP Settings**，只是被打了补丁：它读取上述属性并
移除对应菜单项。证据 —— `Settings.odex` 中存在这个符号：

```
DELETE_ADVANCEDITEM_SUPPORT
```

所以把 `ro.xc_delete_advanced_item` 翻成 `0`，"高级"／开发者选项入口就会重新出现。
AOSP 原有的机制都还在：`development_settings_enabled`、
`Settings$LocalePickerActivity` 等等。

### 2. 第三方安装被 Sunmi 应用商店拦截

在整个 1.5 GB 系统镜像里搜索那条用户可见的错误字符串，只在一个地方找到：

```
FOUND in: .../SunmiAppStore_v3.2.51_release_v1.apk
  "Unauthorized application installation is not allowed."
```

而那个 APK 的清单里写着：

```
package = woyou.market
```

所以 **`woyou.market` 就是安装的守门人**。AOSP 的 `PackageInstaller` 和 `Settings`
在这方面没有被改动 —— Sunmi 是在应用层做安装拦截的。

### 3. 管控体系的包名

| 目录 | 包名 |
|---|---|
| `SunmiAppStore_v3.2.51_release_v1` | **`woyou.market`** —— 拦截未授权安装 |
| `SunmiSecurityService_v2.0.30_release` | **`com.sunmi.sunmisecurityservice_v3`** —— `sunmi/installer/`、`InstallAppObserver` |
| `SunmiSystemIntentIntercept_v1.1.5_release` | **`woyou.system.intent.intercept`** —— 拦截相册/浏览器/拨号/相机/音乐/短信 Intent |
| `SunmiSystemAPI_v1.3.32_release` | **`woyou.system.api`** |

注意 `woyou.*` —— 这是 Sunmi 早期的内部命名空间。

### 4. 其他有用的发现

- 存在 `/app/EngineerMode`、`/app/FactoryMode`、`/app/SecretCode`、`/app/EngineerTests`
  → 可以通过暗码进入 MTK 工程模式。
- `/system/app` 里全是常规 AOSP 应用（Calculator、Camera、Gallery2、Browser、
  DocumentsUI、PrintSpooler……），说明这个 ROM 并没有被大量裁剪。
- `/etc/disableapplist.txt` 只是 MTK 原厂的禁用列表，**不是** Sunmi 的白名单。
- `/system` 里没有任何 `shengfutong` / `sft` 包 → 如果盛付通代理存在，它应该在
  `/data`（未导出；我们有意跳过了 userdata）。

## 对计划的影响

三条面向用户的目标最终归结为两处修改，外加要禁用的一个包：

| 目标 | 机制 |
|---|---|
| 开发者选项 | 修改 `/system/build.prop` 中的 `ro.xc_delete_advanced_item=0`（再配合 `settings put global development_settings_enabled 1`） |
| 第三方安装 | 禁用/移除 **`woyou.market`**（再配合 `install_non_market_apps=1`） |
| 系统语言 | 修改 `/system/build.prop` 中的 `ro.product.locale`；AOSP 的 `LocalePickerActivity` 完好 |
| （附加）非支付行为 | `ro.xc_payment_type=0` |

`/system/build.prop` 位于只读的 dm-verity `/system` 分区上，因此最干净的做法是用
**Magisk 模块**覆盖 `build.prop` —— 完全不需要改动 `/system`，而且能扛过一次 OTA／重刷。
另一种做法是取得 root 后把 `/system` 重新挂载为可写。
