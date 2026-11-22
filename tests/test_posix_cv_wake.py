"""Count Linux futex wakes and exercise SRW and critical-section waits. Run python -I -B tests/test_posix_cv_wake.py.

A wake with no sleeper registered makes no futex call (HOS_CV_WAKE_SKIP=0: every wake does). Linux only: checked by the Linux
runner, not on this Windows PC. Ported from Longshot 7daafa7a (#1553, HumanBean), f92c423b."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "cc"]
RUN_ALL_SKIP = {"windows": "tests the Linux futex implementation"}
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from srccut import between


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    posix = ROOT / "host" / "posix"
    source = (posix / "win32_posix.c").read_text()
    waits = between(source, "static struct timespec rel_ms(", "/* (any size:")
    harness = r"""
#include <windows.h>
#include <assert.h>
#include <limits.h>
#include <linux/futex.h>
#include <sys/syscall.h>
static __thread DWORD last_error;
static unsigned wakes;
static long futex(volatile uint32_t *addr, int op, uint32_t value, const struct timespec *ts) {
    if (op == FUTEX_WAKE_PRIVATE) __atomic_add_fetch(&wakes, 1, __ATOMIC_RELAXED);
    return syscall(SYS_futex, addr, op, value, ts, NULL, 0);
}
"""
    cases = r"""
static CONDITION_VARIABLE cv = CONDITION_VARIABLE_INIT;
static CRITICAL_SECTION cs;
static SRWLOCK lock = SRWLOCK_INIT;
static unsigned waiting;
static int ready;
static void *worker(void *unused) {
    (void)unused;
    AcquireSRWLockShared(&lock);
    __atomic_add_fetch(&waiting, 1, __ATOMIC_RELEASE);
    while (!ready) assert(SleepConditionVariableSRW(&cv, &lock, 2500, CONDITION_VARIABLE_LOCKMODE_SHARED));
    ReleaseSRWLockShared(&lock);
    return NULL;
}
int main(void) {
    InitializeCriticalSection(&cs);
    for (int i = 0; i < 32; i++) {
        WakeConditionVariable(&cv);
        WakeAllConditionVariable(&cv);
    }
    if (wakes) { fprintf(stderr, "%u idle futex wakes\n", wakes); return 1; }
    EnterCriticalSection(&cs);
    assert(!SleepConditionVariableCS(&cv, &cs, 1) && last_error == ERROR_TIMEOUT);
    LeaveCriticalSection(&cs);
    WakeConditionVariable(&cv);
    assert(!wakes);
    for (unsigned n = 1; n <= 8; n += 7) {
        pthread_t threads[8];
        waiting = 0; ready = 0;
        for (unsigned i = 0; i < n; i++) assert(!pthread_create(&threads[i], NULL, worker, NULL));
        while (__atomic_load_n(&waiting, __ATOMIC_ACQUIRE) != n) sched_yield();
        AcquireSRWLockExclusive(&lock);
        ready = 1;
        if (n == 1) WakeConditionVariable(&cv); else WakeAllConditionVariable(&cv);
        ReleaseSRWLockExclusive(&lock);
        for (unsigned i = 0; i < n; i++) assert(!pthread_join(threads[i], NULL));
        unsigned before = wakes;
        WakeAllConditionVariable(&cv);
        assert(wakes == before);
    }
    assert(wakes == 2);
}
"""
    with tempfile.TemporaryDirectory() as temp:
        fixture = Path(temp) / "cv.c"
        fixture.write_text(harness + waits + cases)
        exe = fixture.with_suffix("")
        subprocess.run([args.cc, "-std=gnu11", "-O2", "-pthread", "-I", str(posix), str(fixture), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=12)


if __name__ == "__main__":
    main()
