#!/system/bin/sh
# Sunmi P1 root helper - executed by the kernel as root via core_pattern.
# We drop shell commands into .rcmd and read the output from .rout.
OUT=/data/local/tmp/.rout
IN=/data/local/tmp/.rcmd

{
    echo "=== root helper: $(date) uid=$(id -u) euid=$(id -u) ==="
    id
    cat /proc/version
    echo "selinux: $(cat /sys/fs/selinux/enforce 2>/dev/null)"
    echo "core_pattern: $(cat /proc/sys/kernel/core_pattern 2>/dev/null)"
} >> $OUT 2>&1

if [ -s $IN ]; then
    cp $IN $IN.busy
    : > $IN
    { echo "--- exec $(date) ---"; /system/bin/sh $IN.busy; } >> $OUT 2>&1
fi

chmod 666 $OUT 2>/dev/null
exit 0
