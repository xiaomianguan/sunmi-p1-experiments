# Sunmi P1（W6900，MT6580）—— 通往完全开放的引导加载程序 / 定制 ROM 之路

> **状态（2026-10-16）：历史分析 —— 内容仍然准确，但所有路径都已关闭。**
> Path A–E 都测试过，均被阻断；`VERITY.md` 记录了引导链被硬件锁死的证明。
> 下面的 §5（`persist.sys.usb.config` 死锁）**已经解决**，adb 就是这样拿到的。
> 工作重心此后转移到 `EXPLOITS.md` 中的内核/用户态路线。当前状态见 `README.md`。

> 本文是 `ROM_ANALYSIS.md` 的简体中文译本。

基于证据的分析。以下所有内容都是对照设备自身的分区验证过的，不是来自文档。

## 1. 信任模型的实际样子

```
BootROM（掩膜 ROM，不可更改）
  └─ target_config = 0x0  ->  SBC: False, SLA: False, DAA: False
      => BROM 层面没有任何认证。我们可以完整读写闪存。
  └─ 加载 PRELOADER（boot1 区域）
       └─ preloader 内含一个硬编码的 RSA-2048 公钥 @ 0x1c600
       └─ lk.bin 没有附加签名  <-- 关键观察
  └─ 加载 LK（lk 分区）
       └─ LK 内含同一个硬编码的 RSA-2048 公钥 @ 0x3c478
       └─ LK 用该公钥校验 boot.img / recovery.img
       └─ LK 的链接地址约为 0x81E00000（来自其 rodata 中的指针 0x81E3C26C）
  └─ 加载 boot.img
       └─ 镜像数据之后附加签名 @ 0x76F800：
          SEQUENCE { INTEGER 1, Certificate(973B), SEQUENCE{alg, BIT STRING} }
```

### 签名证书（来自 boot.img）

```
subject : C=SH, ST=ShangHai, L=ZZT, O=XCIT, OU=XCIT, CN=fym, emailAddress=766018769@qq.com
issuer  : 完全相同  -> 自签名
serial  : e1ba302f076819cf
valid   : 2016-11-17 .. 2016-12-17   （一个月，已过期）
key     : RSA 2048, sha256WithRSAEncryption
```

一张自签名证书，带个人 QQ 邮箱，有效期一个月，来自 2016 年 —— 这是开发者临时凑数的东西，
不是 PKI。但这**并不重要**，因为公钥被*烧进了 LK 和 preloader*，证书实际上只是装饰。

### 这意味着什么

* 我们**无法**简单地给自己的镜像签名 —— LK 用它内嵌的公钥做校验。
* 我们**可以**替换那个公钥。它是位于已知偏移处的一段 256 字节模数。那是*数据*修改，
  不是代码补丁：不需要反汇编，而且校验逻辑照常工作 —— 只是改为信任*我们的*公钥。
* 解锁后 LK 报告的 `secure: no` **并不等于**"校验关闭"。校验一直开着。
  `secure` 标志和 `sec_img_verify` 是相互独立的。

### 已证实的阻断点

| 阻断点 | 细节 |
|---|---|
| LK 校验 boot/recovery | 已证明：出厂镜像仅把签名置零就会启动循环 |
| `/system` 上的 dm-verity | 哈希树尾部位于 `0x5f3df000`（magic `0xb001b001`），签名对照 ramdisk 中的 `verity_key` 校验 |
| fstab 写着 `verify` | boot.img 的 ramdisk 内：`/system ... ro wait,verify` |
| seccfg 无法伪造 | V3，由硬件 SEJ 加密；mtkclient 的模拟在 MT6580 上是坏的（777 个 AES 块失败） |
| SECRO 策略 | `SDL configuration[LOCK/UNLOCK]` + `SB configuration[LOCK/UNLOCK]` 记录 —— 已加密 |
| `/system` 是 `ro` + verity | 无法就地修改 build.prop / 移除 `woyou.market` |

## 2. 通往完全开放的各条路径（按优先级排序）

### Path A —— 替换 LK 中硬编码的公钥（推荐）

1. 生成我们自己的 RSA-2048 密钥对 + 自签名证书。
2. 用我们的模数覆盖 `lk.bin:0x3c478` 处的 256 字节模数。
3. 刷入修改后的 LK。
4. 用我们的私钥、按 MTK 的格式给自己的 boot/recovery 镜像签名。

* **优点**：完全不需要打代码补丁；校验路径原封不动地继续工作，只是改为对照我们的密钥。
  一旦完成，*任何*我们签名的东西都能启动。
* **缺点**：仍需要知道确切的签名数据格式（这是唯一未知项 —— 签名不是针对原始镜像，
  而是对一个结构签名）。
* **唯一的阻断点**：preloader 是否接受被修改的 LK。

### Path B —— 给 LK 打补丁以跳过 `sec_img_verify`

* 找到校验调用并把它短路（`mov r0,#0; bx lr`）。
* **优点**：确定性做法；完全不需要知道签名格式。
* **缺点**：需要代码逆向。现在可行性高多了：LK 基址约 `0x81E00000`，而且加密相关与
  密钥 rodata 集中在文件 `0x3a000–0x3c600`，引用它们的代码就在附近。

### Path C —— 顺便给 preloader 的公钥也打补丁（大概不需要）

* 只有当 preloader 会校验 LK 时才需要。证据表明它不校验（LK 没有签名）。
* 如果它确实校验：preloader 是由 BROM 校验的，而 BROM 的 SBC 是关闭的 ——
  所以 preloader 本身也可以打补丁。

### Path D —— 关闭 dm-verity（会自动实现）

一旦 A/B 中任意一条走通，我们就能刷入一个定制 boot.img，它会：

* 从 `fstab.mt6580` 中移除 `verify`，**并且**
* 在内核命令行后追加 `androidboot.veritymode=disabled`
  （当前命令行：`bootopt=64S3,32S1,32S1`）。

这样 `/system` 就会在没有 dm-verity 的情况下挂载 → 完全可编辑 → 去 Sunmi 化的 ROM、
修好 `build.prop`、移除 `woyou.market`、安装 Magisk。

### Path E —— 真正的定制 ROM

* 内核是 **Linux 3.18.19**（MTK alps，2018-03-19 构建，GCC 4.8）；完整的 `vmlinux`
  已经提取出来（14.5 MB）。
* MTK 为 MT6580 公开了 alps 内核源码，所以定制**内核**是可行的。
* 但打印机 / 扫描仪 / NFC / 支付 HAL 都是专有的，而且 3.18 内核无法承载现代 Android。
* **现实上限**：一个经过大量修改的*基于原厂*的 ROM（Android 6/7）—— 这正是
  Path A–D 所交付的东西。在这套硬件上，LineageOS 20 永远不可能。

### Path F —— 其他值得检查的杠杆

* `mtk.py da efuse` —— 读取熔丝状态（SBC / secure boot），确认没有任何东西被熔断锁死。
* 解锁后在一个*全新的* LK 实例上是否允许 `fastboot flash`（之前的拒绝来自一个仍在持有
  锁定策略的旧实例）。
* SECRO 的 `SB/SDL` LOCK 与 UNLOCK 记录 —— 如果它们就是策略来源且可解密，那又是另一个杠杆。

## 3. 眼下那个决定性的测试

**`lk_patched_test.img`** —— 出厂 `lk.bin`，只改了一个字符串：

```
"Select Boot Mode:"  ->  "***LK PATCHED***:"     （17 字节；其他什么都没动）
```

刷进去，然后按住音量加开机。如果菜单显示 `***LK PATCHED***:`，就说明 preloader 接受并
执行了被修改的 LK，Path A 和 Path B 就都打开了。
安全性：改一个字符串不可能弄坏 LK，而且写一次就能恢复出厂 `lk.bin`。

## 4. 推荐的顺序

1. 完成 `/data` 修改 → 拿到 shell（进行中；立刻让设备变得可用）。
2. 做 LK 字符串测试 → 证明被修改的 LK 会被接受。
3. Path A：把 LK 的 RSA 模数换成我们的（需要签名数据格式，而 Path B 的逆向也会揭示它）。
4. Path D：刷入定制 boot（关闭 verity）→ 去 Sunmi 化 + Magisk。
5. 可选 Path E：修改版原厂 ROM / 定制内核构建。

## 5. 拿到 shell：`persist.sys.usb.config` 死锁（已解决）

这*不是*常见的"开发者选项被隐藏"问题。开发者选项被隐藏并不会阻止 adb。
这台设备在 `UsbDeviceManager` 里有一个**逻辑死锁**，使得单独设置 `adb_enabled=1` 毫无作用。

### 证据

从真实的 Android 6.0.1 源码读出
（`services/usb/java/com/android/server/usb/UsbDeviceManager.java`），
并与本 ROM 自己的 `/system/framework/oat/arm/services.odex` 交叉核对
（其中包含 `applyAdbFunction`、`removeFunction`、`addFunction`、`persist.sys.usb.config`、
`ADB_ENABLED is restricted`、`Failsafe 3` —— 也就是说 Sunmi **没有**删掉这段逻辑）：

```java
// UsbHandler 构造函数
mAdbEnabled = UsbManager.containsFunction(getDefaultFunctions(), USB_FUNCTION_ADB);

private String getDefaultFunctions() {                 // 读取 persist.sys.usb.config
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

死锁是这样闭合的：

1. ramdisk 里的 `default.prop` 出厂即 `persist.sys.usb.config=mtp`（Sunmi 删掉了 `,adb`），
   所以开机时 `getDefaultFunctions()` = `"mtp"`。
2. 因此 `mAdbEnabled = false`。
3. 因此 `systemReady()` **写入 `adb_enabled = 0`** —— 静默地把我们打进
   `settings_global.xml` 的 `adb_enabled=1` 撤销掉。
4. `setAdbEnabled()` 只在*设置发生变化*时运行；而框架自己刚把它强制设成 0，
   且 `mAdbEnabled` 本来就是 false，所以永远不会触发变更事件。

所以 `adb_enabled` 是那个属性的*结果*，不是杠杆。唯一的杠杆是属性本身：

```
/data/property/persist.sys.usb.config = mtp,adb
```

只要这个文件存在，开机时 `mAdbEnabled = true`，框架自己会把 `adb_enabled` 设成 1，
`sys.usb.config` 变成 `mtp,adb` → `init.usb.rc` 启动 `adbd`，主机看到的就是
`0e8d:201d` 而不是 `0e8d:2008`。

### 为什么我们不用最显然的办法创建这个文件

`debugfs write` 会分配一个 inode、一个数据块和一个目录项，因此也会重写**块位图、inode 位图、
组描述符以及超级块的空闲计数**。我们的离线镜像是设备关机时抓的快照；此后 Android 一直在往
`/data` 写，所以把这些分配计数器原样回放，会让分配器以为正在使用的块是空闲的 ——
也就是可能把它们再次分配出去，破坏正在使用的文件。

### 我们实际使用的补丁：一个硬链接，40 字节，不触碰分配器状态

`/data/property` 里已经有属性文件，而 ext4 的目录块有大量空隙（最后一个目录项的 `rec_len`
覆盖了块的剩余部分）。于是我们**追加一个目录项**指向一个*已存在的* inode，并给该 inode 写入
我们的值：

| 块 | 内容 | 改动 |
|---|---|---|
| 655872 | `/property` 目录块 | 最后一条记录的 `rec_len` 3588→28，新增目录项 `ino=163216 rec_len=3560 name_len=22 type=1` |
| 655362 | 第 20 组的 inode 表第 0 块（inode 163216，偏移 `0xf00`） | `i_size_lo` 1→7，`i_links_count` 1→2 |
| 658946 | 被链接文件的数据块 | `"2"` → `"mtp,adb"` |

没有任何分配发生，所以**分配器的元数据一个比特都没被改动** —— 没有位图、没有组描述符、
没有超级块。这让该补丁完全不受"快照过期"问题的影响，也不受日志回放撤销的影响
（部分回滚最多退化成"属性没设上"，绝不会变成损坏）。

唯一的副作用是：被链接的那个属性 `persist.sys.pq.shp.idx`（显示锐度索引，按 `int` 读取）
现在读到的是 `"mtp,adb"` → `0`。没有损失。

工具：`tools/make_property_patch.py`（默认值：`--link=/property/persist.sys.pq.shp.idx`、
`--property=persist.sys.usb.config`、`--value=mtp,adb`）。

### 刷入前所做的验证

* 对打过补丁的镜像执行 `debugfs -R "cat /property/persist.sys.usb.config"` → `mtp,adb`
* `debugfs -R "stat"` → inode 163216，大小 7，链接数 2，extent 不变
* 载荷与原始文件的字节差异 → 31 + 2 + 7 = 40 字节，全部有解释
* **对打过补丁的镜像执行 `e2fsck -fn`，输出与未打补丁的基线逐字节相同**
  （同样只有一条既有的抱怨 "Padding at end of inode bitmap is not set"，同样 956 个 inode，
  同样 59882 个块）→ 该补丁没有引入任何新的文件系统问题

### 操作流程（两次 BROM 会话，中间设备始终不开机）

1. `./brom_read_live.sh` —— 只读。读取那 3 个目标块*以及*两个 `settings_global.xml` 块，
   这样我们可以确认实机 `/property` 目录没变、且之前的补丁仍然完好。刻意**不**做 `reset`。
2. 与快照对比；确认无误后才
3. `./brom_write_prop.sh` —— 写入这 3 个块，读回、验证、重启。
   回滚：`./brom_write_prop.sh --restore`。
