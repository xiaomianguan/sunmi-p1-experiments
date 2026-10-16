# HANDOFF — Sunmi P1 root via CVE-2019-2215 (agent-facing)

This file is written for an **AI agent continuing the work**, not for a human reader. It is
deliberately not translated. For the human-facing overview see `README.md`; for the full
research log see `EXPLOITS.md` (Updates 1–6) and `VERITY.md`.

## 1. Objective

Get root on a **Sunmi P1 / W6900** (MT6580, armv7l, Linux 3.18.19, Android 6.0.1) via
**CVE-2019-2215** (binder UAF). The boot chain is proven hardware-locked (see `VERITY.md`),
so kernel/userspace is the only route. Endgame: patch `core_pattern` to
`|/data/local/tmp/.r.sh`, crash a process, and let the kernel run the helper as root
(`tools/rootshell.sh`; it executes commands left in `/data/local/tmp/.rcmd` and logs to
`.rout`).

## 2. State: what is proven and what is open

**Proven on-device:**

1. **Fixture present** — `binder_poll` @ `c06fbc24` calls `poll_wait` on two waitqueues with
   no `POLLFREE` handling; `binder_free_thread` @ `c06f9564` ends in `bl kfree`.
2. **Trigger path reached** — `binder_poll` takes the vulnerable
   `poll_wait(&thread->wait)` branch (only taken while
   `transaction_stack != 0 && todo == empty`), the epoll entry lands on `thread->wait`, and
   `BINDER_THREAD_EXIT` `kfree()`s that `binder_thread`. Live evidence:
   `[txn read 8]: 0x0000720c 0x00007206` then `[+] epoll entry registered on thread->wait`.
3. **Heap reclaim works** — the freed `binder_thread` is reclaimed by a 32-entry (256 B) or
   64-entry (512 B) **kernel-side iovec array** from `recvmsg`/`writev`. Proof: the DEL
   completes without a BUG, which requires the lock at chunk+0x2C to be 0 = our
   `iov[5].iov_len`. At 1024 B it misses and panics.
4. **Both target addresses are correct** (verified against the kernel image, not guessed):
   `core_pattern` = **0xc0cdf4c4** (the `.data` field of its `ctl_table` at `c0cd4ff8`;
   `.procname` = `c0aa3980`, `maxlen` 0x80, mode 0644) and `selinux_enforcing` =
   **0xc0e44738** (`sel_write_enforce` @ `c0232720` builds `r5 = 0xc0e44738`).

**Open — the only remaining item:**

5. **No arbitrary write yet.** The `list_del` in `remove_wait_queue` is the wrong primitive
   on arm32. See §4.

## 3. Exact oracles (use these, they are cheap and unambiguous)

| Oracle | Meaning |
|---|---|
| `x w <segs> <addr> <value>` then `adb shell uname -a` | Write to `init_uts_ns.name.sysname` (**0xc0cd0de0**) and read it back through the `uname(2)` **syscall**, which SELinux cannot filter. If `uname` still prints `Linux`, the write did **not** land. |
| **Kernel panic = reclaim MISS; clean DEL = reclaim HIT** | `CONFIG_DEBUG_SPINLOCK` is on, so a garbage lock in `remove_wait_queue` **BUGs and panics** instead of spinning. `Internal error: Oops - BUG: 0 ... (_raw_spin_lock_irqsave) from (remove_wait_queue+0x18)` in `/proc/last_kmsg` = miss. |
| `/sys/fs/selinux/enforce` | `1` = the `selinux_enforcing` write did not take. |
| `/data/local/tmp/.rout` | The ultimate success signal after the crash trigger. |

Note: a **HIT from `kw4` is necessary but not sufficient** — it only proves the lock was
readable as 0, not that our array occupied the chunk. Always confirm with `uname`.

## 4. The open problem: the arm32 write primitive

Do **not** re-attempt the `epoll_ctl(DEL)` → `remove_wait_queue` → `list_del` write; it is
provably chunk-internal:

* `ep_unregister_pollwait` → `ep_remove_wait_queue(pwq)` →
  `remove_wait_queue(pwq->whead, &pwq->wait)`. The `wait_queue_t` being deleted lives in the
  **`eppoll_entry` (`pwq`)** — a separate `eventpoll_pwq` slab — and its `task_list` was set
  by `add_wait_queue` to `&wq->task_list` = **chunk+0x30**, a fixed value stored in the pwq.
* `list_del` therefore does `*(chunk+0x30+4) = chunk+0x30` and `*(chunk+0x30) = chunk+0x30`:
  it writes the chunk's own address into the chunk and nothing else.
* Offset note: on arm32 `next->prev` is at **+4** (0x34) vs arm64's **+8** (0x38). That is why
  the public arm64 PoC's leak stage works there (the self-pointer lands in `iov[6].iov_base`,
  so the still-running `writev` reads kernel memory) and not here (it lands in
  `iov[6].iov_len`, a length).
* The PoC's write stage is also unavailable: it points `iov_base` at a kernel address and
  relies on arm64's `copy_to_user` having **no `access_ok`**. arm32's `copy_to_user` **does**
  check `access_ok` (`__range_ok` vs `current_thread_info()->addr_limit`), so a kernel
  destination returns EFAULT. No iovec-based kernel R/W on armv7.

### Where the primitive has to come from instead

The freed `binder_thread` remains referenced by the transaction parked on the target thread,
so the **binder driver keeps operating on it**, and its list operations use *our* iovec
values as list pointers — a real kernel store with no user-copy validation:

* `binder_thread_read` / `binder_transaction` do `list_add`/`list_del` on **`thread->todo`
  (chunk+0x24)**. `list_add(&new, head)` performs `head->next->prev = new`, i.e.
  **`*(our_iov_value + 4) = &t->work`** — arbitrary *address*, kernel pointer value.
* `binder_transaction` also calls `wake_up_interruptible_sync(&thread->wait)` on the freed
  thread → `__wake_up_common` walks `q->task_list` (our chunk) and calls
  `curr->func(curr, mode, wake_flags, key)` → a **controlled function-pointer call**
  (`wait_queue_t.func` is at offset 8; `task_list` at 0x0C in 3.18).

Suggested chain: use the arbitrary-address write to set **`addr_limit`** in our
`thread_info` to a large value (a leaked heap pointer is enough — `access_ok` only needs the
limit to be above the kernel text/data region). Once `addr_limit` is raised, plain
`read()`/`write()` to `core_pattern` (0xc0cdf4c4) and `selinux_enforcing` (0xc0e44738) works
and the endgame in §1 follows directly.

Next concrete steps, in order:

1. Determine how to *re-trigger* the binder path so the driver touches the freed thread
   **after** the reclaim (the current code only ever triggers the epoll DEL). Inspect
   `binder_transaction` / `binder_thread_read` (disassembly in `/tmp/kernel.dis`) for the
   exact list operations and which of them are reachable from our open binder fd.
2. Build the `thread->todo` write: set `iv[6]`/`iov[...]` so the list head pointer is
   `target-4`, then trigger. Verify with the `sysname` oracle first, then aim at
   `selinux_enforcing`.
3. Alternatively work the `wake_up_interruptible_sync` route (`curr->func`) — it gives PC
   control but needs a known kernel address holding a fake `wait_queue_t`, which needs a
   leak of the chunk address (the `list_del` self-pointer write can provide it if the read
   direction can be recovered).

## 5. Verified data (do not re-derive)

```
base c0008000, 1:1 VA<->file offset, no KASLR, CONFIG_MODULES=n, CONFIG_KALLSYMS_ALL=n

binder_poll            c06fbc24        binder_release      c06f6ed8
binder_ioctl           c070015c        binder_free_thread  c06f9564
ep_poll_callback       c017fcd0        sel_write_enforce   c0232720
commit_creds           c00466e0        prepare_kernel_cred c0046c8c
sys_call_table         c000f524        do_coredump         c018e698

sizeof(binder_thread)  0xFC  (kmalloc-256 per kmalloc_index, though binder_free_thread
                              loads its cache from kmalloc_caches+36 = index 9 = 512)
sizeof(binder_proc)    0x15C
binder_thread:  proc 0, rb_node 4, pid 16(0x10), looper 20(0x14), transaction_stack 24(0x18),
                todo 28(0x1C), return_error 36(0x24), wait 0x2C (lock 0x2C, task_list 0x30),
                stats 0x38
binder_proc:    pid 0x18, tsk 0x24, todo 0x60, wait 0x68
task_struct:    real_cred 0x3F8, cred 0x3FC
struct iovec (armv7): 8 bytes  -> 32 segs = 256 B, 64 segs = 512 B

targets:  selinux_enforcing  0xc0e44738
          core_pattern       0xc0cdf4c4   (maxlen 0x80)
          sysname            0xc0cd0de0   (oracle, read via uname(2))
          nodename           0xc0cd0e21

binder constants (armv7): BC_TRANSACTION 0x40286300, BR_TRANSACTION 0x80287202,
  BR_REPLY 0x80287203, BR_TRANSACTION_COMPLETE 0x7206, BR_FAILED_REPLY 0x7211,
  BR_DEAD_REPLY 0x7205, BR_OK 0x7201, BC_ENTER_LOOPER 0x630c, BC_ACQUIRE 0x40046302,
  BINDER_THREAD_EXIT 0x40046208
```

## 6. Environment and gotchas (each one cost a debugging session)

**Device access**

* adb is available and persists across reboots (`persist.sys.usb.config=mtp,adb` was patched
  into `/data` over BROM). Serial `P121184J00108`.
* **After a panic the adb *server* goes stale** — `adb kill-server && adb start-server`
  restores it. The P1 appearing as `0e8d:201d` / `"P1N"`, `bDeviceClass 00`, interface
  `ff/42/01`, 480 Mbps is the **normal booted** state (the `ff/42/01` interface *is* adb).
  Do **not** power-cycle or reach for BROM recovery on that basis.
* Run the exploit **in the app domain**: `run-as cc.wuersan008.smprint`, binary copied into
  `/data/data/cc.wuersan008.smprint/` and `chmod 700`. `shell` cannot kill app-uid processes
  and the app domain is what the exploit was validated in. Use fresh filenames when pushing.
* `cc.wuersan008.smprint` is the **installed** test app; its source is a separate repo, not in
  this tree (see `.gitignore`).

**BROM / boot chain**

* **Exactly one mtkclient session per power cycle** — the MT6580 BootROM only answers the
  plug-in handshake in a short window after enumeration; a second process sees an
  already-enumerated BROM, assumes it is connected, and fails forever.
* Unplug USB before starting any `brom_*` script; it waits for the device to appear.
* Rollbacks: `./brom_write.sh lk dumps/lk.bin`,
  `./brom_write_boot1.sh --restore`, `./brom_write_verity.sh --restore`,
  `./brom_write_prop.sh --restore`. `dumps/preloader_boot1.bin` is the known-good preloader.

**Binder / exploit specifics**

* A bare binder client is rejected — mimic libbinder's `ProcessState::open()`:
  `ioctl(BINDER_VERSION)`, `ioctl(BINDER_SET_MAX_THREADS)`, **`mmap(fd, 1 MB)`**.
* `String16` needs a **trailing NUL** (`[u32 len][chars][u16 0]`) and 4-byte alignment, or
  servicemanager answers status `-1`.
* `BINDER_WRITE_READ` reports the byte count in `bwr.read_consumed`, **not** in the ioctl
  return value.
* musl's `signal()` sets `SA_RESTART`, which makes an interrupted binder read restart
  forever — install the handler with `sigaction` and `sa_flags = 0`.
* **Never send a one-way transaction to servicemanager** — it crashes it (observed;
  servicemanager + system_server restarted, PIDs changed, device recovered).
* The reply race is won with a helper that first sends a ~1 MB transaction to the
  single-threaded servicemanager, delaying our own reply.
* `BC_ACQUIRE 0` returns EINVAL (no ctxmgr special case in this kernel) ⇒ the local-node
  trick is dead. Binder's `transfer` LSM check denies `BINDER_TYPE_BINDER` for both `shell`
  and `untrusted_app` ⇒ node creation is dead too. Both were already ruled out — do not
  retry them.

## 7. Files

| Path | Why it matters |
|---|---|
| `tools/x.c` | **the exploit to continue**. `x w <segs> <addr> <value>` = one 4-byte write attempt; `x leak <segs>` = diagnostic (destructive: it clobbers the reclaimed chunk); plain `x` = full chain |
| `tools/sunmi2215.c` | earlier revision, incoherent (reference only) |
| `tools/rootshell.sh` | root helper for the `core_pattern` endgame |
| `EXPLOITS.md` | full research log, Updates 1–6 — read before changing anything |
| `VERITY.md` | why the boot chain is a dead end (do not redo those experiments) |
| `README.md` | human-facing overview, status, script reference |
| `./kernel` | extracted ARM Image, base `c0008000`, 1:1 VA↔offset |
| `/tmp/vmlinux.elf` | 50,250 text symbols (no data symbols) |
| `/tmp/kernel.dis` | full disassembly — the source of every offset above |
| `dumps/` | full device backup incl. `preloader_boot1.bin` (recovery) |

Build and run:

```sh
TC=toolchain/arm-linux-musleabi-cross/bin/arm-linux-musleabi-gcc
$TC -static -O2 -o /tmp/x tools/x.c
P=cc.wuersan008.smprint
adb push /tmp/x /sdcard/xN && \
adb shell "run-as $P cp /sdcard/xN /data/data/$P/xN; run-as $P chmod 700 /data/data/$P/xN" && \
adb shell "run-as $P /data/data/$P/xN w 32 0xc0cd0de0 0x214e5750" && adb shell uname -a
```

Note `/tmp/vmlinux.elf` and `/tmp/kernel.dis` live in `/tmp` and may not survive a host
reboot; regenerate them from `./kernel` (`vmlinux-to-elf` + `objdump -d`).

## 8. Do-not-redo list

* Do not retry the boot chain (LK key swap, LK string patch, preloader patch, dm-verity
  TLV, `adb disable-verity`) — all proven dead in `VERITY.md`.
* Do not retry platform-signature impersonation, Tencent Tinker patch injection, MTK
  cmdq/`CVE-2020-0069`, or `/proc/kallsyms` address leaks — all ruled out with evidence in
  `EXPLOITS.md`.
* Do not attempt the `list_del` write again (see §4), and do not trust a `kw4` HIT without
  confirming with the `sysname` oracle.
* Do not send one-way transactions to servicemanager.
