"""Regression test for issue #1060.

Scalene profiles wall-clock time by default, delivering SIGALRM periodically --
including while the process is blocked in a native syscall. poll(2)/select(2)
are *never* restarted by SA_RESTART (signal(7)), so the timer makes them fail
with EINTR. Native libraries that don't retry (e.g. the ODBC driver's
connect-with-timeout path) then break: pyodbc reported WSAEINTR (10004) /
SQLSTATE 08S01.

libscalene (LD_PRELOADed when memory profiling is on, the default) interposes
the non-restartable wait calls and retries them on EINTR -- but only when one of
Scalene's own timer signals caused the interruption, so SIGINT/Ctrl-C and other
signals still propagate. The logic lives in ``src/include/eintr_retry.hpp``.

On POSIX, this test compiles a tiny interposer from that real header (mirroring
how libscalene.cpp wires it up), preloads it into a C program that arms a 5ms
ITIMER_REAL like Scalene, and checks:

  * a 400ms poll()/select() runs to completion instead of dying with EINTR, and
  * SIGINT still interrupts a blocking poll() (the guard does not swallow it).

On Windows there is no interposer -- Scalene samples via threads, not signals,
so blocking syscalls are never interrupted and the bug cannot occur. The
Windows test is the positive counterpart: it profiles a blocking TCP round-trip
under ``scalene run`` and asserts it completes successfully, guarding against a
regression that would reintroduce signal-style interruption on Windows.
"""

import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER_DIR = os.path.join(REPO_ROOT, "src", "include")
HEADER = os.path.join(HEADER_DIR, "eintr_retry.hpp")
MACINTERPOSE_DIR = os.path.join(
    REPO_ROOT, "vendor", "Heap-Layers", "wrappers"
)

skip_on_windows = pytest.mark.skipif(
    sys.platform == "win32",
    reason="EINTR-retry interposers are POSIX-only",
)
windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-specific behaviour (thread-based sampling)",
)


def _cxx():
    for cand in ("c++", "clang++", "g++"):
        path = shutil.which(cand)
        if path:
            return path
    return None


def _cc():
    for cand in ("cc", "clang", "gcc"):
        path = shutil.which(cand)
        if path:
            return path
    return None


# Mirrors the exported interpose entry points in libscalene.cpp (poll/select/
# setitimer are enough to exercise the mechanism cross-platform).
INTERPOSE_CPP = """
#include "eintr_retry.hpp"
#if defined(__APPLE__)
#define LOCAL_PREFIX(x) xx##x
#include "macinterpose.h"
#else
#define LOCAL_PREFIX(x) x
#endif
#define ATTRIBUTE_EXPORT __attribute__((visibility("default")))

extern "C" ATTRIBUTE_EXPORT int LOCAL_PREFIX(setitimer)(
    int which, const struct itimerval *nv, struct itimerval *ov) {
  return scalene::eintr::setitimer_impl(which, nv, ov);
}
extern "C" ATTRIBUTE_EXPORT int LOCAL_PREFIX(poll)(
    struct pollfd *fds, nfds_t nfds, int timeout) {
  return scalene::eintr::poll_impl(fds, nfds, timeout);
}
extern "C" ATTRIBUTE_EXPORT int LOCAL_PREFIX(select)(
    int nfds, fd_set *r, fd_set *w, fd_set *e, struct timeval *t) {
  return scalene::eintr::select_impl(nfds, r, w, e, t);
}
#if defined(__APPLE__)
MAC_INTERPOSE(xxsetitimer, setitimer);
MAC_INTERPOSE(xxpoll, poll);
MAC_INTERPOSE(xxselect, select);
#endif
"""

# C program that mimics Scalene's wall-clock sampler: a one-shot interval timer
# re-armed from the SIGALRM handler via setitimer() on every tick (exactly what
# ScaleneSignalManager.restart_timer does). The interposer's guard keys off that
# setitimer re-arm, so the workload must reproduce it -- a plain periodic
# it_interval timer (armed once) would not.
#
# Phase 1 blocks in poll()/select() for 400ms on a pipe that never becomes
# readable: with the timer firing every 5ms, each EINTR must be retried so the
# wait runs to completion. Phase 2 disarms the timer and confirms SIGINT (not a
# Scalene timer signal) still interrupts poll().
PROG_C = r"""
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t alarms = 0;
static void rearm(void){  /* one-shot 5ms, like restart_timer() */
  struct itimerval it;
  it.it_interval.tv_sec=0; it.it_interval.tv_usec=0;
  it.it_value.tv_sec=0;    it.it_value.tv_usec=5000;
  setitimer(ITIMER_REAL,&it,NULL);
}
static void on_alarm(int s){(void)s; alarms++; rearm();}
static volatile sig_atomic_t sigints = 0;
static void on_sigint(int s){(void)s; sigints++;}
static long now_ms(void){
  struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
  return t.tv_sec*1000L + t.tv_nsec/1000000L;
}

int main(void){
  int p[2]; if(pipe(p)){perror("pipe");return 2;}
  struct sigaction sa; memset(&sa,0,sizeof sa);
  sa.sa_handler=on_alarm; sa.sa_flags=SA_RESTART;
  sigaction(SIGALRM,&sa,NULL);
  rearm();

  /* Phase 1a: poll must run the full timeout despite the timer. */
  struct pollfd pfd={p[0],POLLIN,0};
  long t0=now_ms();
  int r=poll(&pfd,1,400);
  long e=now_ms()-t0;
  int poll_ok = (r==0 && e>=380);
  printf("poll ret=%d errno=%s elapsed=%ldms alarms=%d ok=%d\n",
         r, r<0?strerror(errno):"-", e, (int)alarms, poll_ok);

  /* Phase 1b: same for select. */
  fd_set rs; FD_ZERO(&rs); FD_SET(p[0],&rs);
  struct timeval tv={0,400000};
  t0=now_ms();
  r=select(p[0]+1,&rs,NULL,NULL,&tv);
  e=now_ms()-t0;
  int select_ok = (r==0 && e>=380);
  printf("select ret=%d errno=%s elapsed=%ldms ok=%d\n",
         r, r<0?strerror(errno):"-", e, select_ok);

  /* Phase 2: with the timer disarmed, SIGINT must still interrupt poll
     (the guard only absorbs EINTR attributable to a Scalene timer re-arm). */
  struct itimerval off; memset(&off,0,sizeof off);
  setitimer(ITIMER_REAL,&off,NULL);
  memset(&sa,0,sizeof sa); sa.sa_handler=on_sigint; sa.sa_flags=0;
  sigaction(SIGINT,&sa,NULL);
  pid_t pid=fork();
  if(pid==0){
    struct timespec d={0,100*1000000L}; nanosleep(&d,NULL);
    kill(getppid(),SIGINT); _exit(0);
  }
  t0=now_ms();
  r=poll(&pfd,1,2000);
  e=now_ms()-t0;
  int sigint_ok = (r<0 && errno==EINTR && sigints>0 && e<1000);
  printf("sigint ret=%d errno=%s elapsed=%ldms sigints=%d ok=%d\n",
         r, r<0?strerror(errno):"-", e, (int)sigints, sigint_ok);

  return (poll_ok && select_ok && sigint_ok) ? 0 : 1;
}
"""


def _dll_suffix():
    return ".dylib" if sys.platform == "darwin" else ".so"


@skip_on_windows
def test_eintr_retry_survives_timer_but_not_sigint(tmp_path):
    cxx = _cxx()
    cc = _cc()
    if not cxx or not cc:
        pytest.skip("no C/C++ compiler available")
    if not os.path.exists(HEADER):
        pytest.skip("eintr_retry.hpp not present")

    src = tmp_path / "interpose.cpp"
    src.write_text(INTERPOSE_CPP)
    lib = tmp_path / ("libinterpose" + _dll_suffix())

    cxx_cmd = [
        cxx,
        "-std=c++14",
        "-O2",
        "-fvisibility=hidden",
        f"-I{HEADER_DIR}",
        f"-I{MACINTERPOSE_DIR}",
        "-shared" if sys.platform != "darwin" else "-dynamiclib",
    ]
    if sys.platform != "darwin":
        cxx_cmd.append("-fPIC")
    cxx_cmd += [str(src), "-o", str(lib), "-ldl", "-lpthread"]
    try:
        subprocess.run(cxx_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"could not build interposer: {exc.stderr}")

    prog_c = tmp_path / "prog.c"
    prog_c.write_text(PROG_C)
    prog = tmp_path / "prog"
    try:
        subprocess.run(
            [cc, "-O0", str(prog_c), "-o", str(prog)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"could not build test program: {exc.stderr}")

    env = dict(os.environ)
    if sys.platform == "darwin":
        env["DYLD_INSERT_LIBRARIES"] = str(lib)
    else:
        env["LD_PRELOAD"] = str(lib)

    # Baseline (no interposer): the timer must break poll with EINTR, proving
    # the scenario is real on this machine. If it doesn't reproduce (timing),
    # skip rather than give a false pass.
    baseline = subprocess.run(
        [str(prog)], capture_output=True, text=True, timeout=30
    )
    if "ok=1" in baseline.stdout.splitlines()[0]:
        pytest.skip(
            "timer did not interrupt poll on this machine; "
            f"cannot validate the fix. baseline:\n{baseline.stdout}"
        )

    # With the interposer preloaded, all three checks must pass.
    result = subprocess.run(
        [str(prog)], capture_output=True, text=True, env=env, timeout=30
    )
    assert result.returncode == 0, (
        "EINTR-retry interposer failed:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # Be explicit about which property held, for debugging on failure.
    lines = {ln.split()[0]: ln for ln in result.stdout.splitlines() if ln}
    assert "ok=1" in lines.get("poll", ""), result.stdout
    assert "ok=1" in lines.get("select", ""), result.stdout
    assert "ok=1" in lines.get("sigint", ""), result.stdout


# Workload run under `scalene run` on Windows: a blocking TCP round-trip,
# repeated while burning CPU so the (thread-based) sampler is active. On Windows
# this must complete cleanly -- there is no signal that could interrupt the
# blocking connect/recv the way SIGALRM does on Linux (issue #1060).
WINDOWS_WORKLOAD = r"""
import socket, threading, sys

HOST = "127.0.0.1"
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((HOST, 0))
srv.listen(8)
port = srv.getsockname()[1]

def serve():
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5.0)
            data = conn.recv(64)
            if data:
                conn.sendall(data)

t = threading.Thread(target=serve, daemon=True)
t.start()

ROUNDTRIPS = 200
ok = 0
for i in range(ROUNDTRIPS):
    c = socket.create_connection((HOST, port), timeout=5.0)  # blocking connect
    try:
        msg = ("ping-%d" % i).encode()
        c.sendall(msg)
        if c.recv(64) == msg:                                # blocking recv
            ok += 1
    finally:
        c.close()
    # Burn CPU between round-trips so the sampler fires during the run.
    s = 0
    for j in range(20000):
        s += j * j

assert ok == ROUNDTRIPS, "only %d/%d round-trips succeeded" % (ok, ROUNDTRIPS)
print("ROUNDTRIP_OK", ok)
sys.stdout.flush()
"""


@windows_only
def test_blocking_socket_roundtrip_under_scalene_windows(tmp_path):
    """On Windows, profiling a blocking socket workload must not break it.

    This is the positive counterpart to the POSIX EINTR test: it confirms that
    Scalene's thread-based Windows sampler leaves blocking connect()/recv()
    untouched, so the issue #1060 failure mode does not occur here.
    """
    workload = tmp_path / "workload.py"
    workload.write_text(WINDOWS_WORKLOAD)
    out = tmp_path / "profile.json"

    cmd = [
        sys.executable,
        "-m",
        "scalene",
        "run",
        "--cpu-only",
        "-o",
        str(out),
        str(workload),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, (
        "scalene run failed on Windows:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ROUNDTRIP_OK" in result.stdout, (
        "blocking socket round-trip did not complete under scalene:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
