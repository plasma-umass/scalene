"""Programs that wait for a signal must not hang under Scalene.

In wall-clock mode (the default) Scalene's SIGALRM timer is one-shot and
re-armed by its Python handler, which also delivers the program's own
setitimer() signals (replacement_signal_fns.py). Two ways that broke:

* Since #1140 the C signal handler re-arms a CPU-time timer while the Python
  handler is pending. Through libscalene's setitimer interposer that counted
  as "Scalene's handler ran", so the EINTR-retry interposer (#1060) retried a
  Python-level wait (select.poll(), select.select()) in C, and CPython never
  ran the handler: a wait for the program's own alarm hung every time.
* If Scalene's signal lands just before a wait begins, CPython only runs the
  handler once the wait ends, and nothing was armed to end it (seen as a hang
  of test/signal_test.py on CI). The timer now reloads every second until the
  handler re-arms it.
"""

import shutil
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Earlier tests may start Scalene in this process, which replaces
# signal.signal/setitimer with versions that emulate the program's timers;
# the in-process tests below need the real ones.
import _signal  # noqa: E402

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Unix timer signals (Windows uses a thread)"
)

HELPER_C = r"""
#include <time.h>
#include <unistd.h>

static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}

/* Busy C code: CPython can't run a Python signal handler until it returns. */
void spin(double seconds) {
  double end = now() + seconds;
  while (now() < end) {
  }
}

/* A timer signal arriving during the spin is handled at the C level only; the
   Python handler stays pending, so the wait begins with the signal already
   spent: the race, every time. */
void spin_then_pause(double seconds) {
  spin(seconds);
  pause();
}
"""


@pytest.fixture(scope="module")
def helper(tmp_path_factory: pytest.TempPathFactory) -> Path:
    cc = next((p for c in ("cc", "clang", "gcc") if (p := shutil.which(c))), None)
    if cc is None:
        pytest.skip("no C compiler")
    d = tmp_path_factory.mktemp("timer_wakeups")
    src = d / "helper.c"
    src.write_text(HELPER_C)
    lib = d / "helper.so"
    subprocess.run(
        [cc, "-shared", "-fPIC", "-O0", "-o", str(lib), str(src)], check=True
    )
    return lib


def _scalene(
    tmp_path: Path, program: str, *options: str
) -> subprocess.CompletedProcess:
    script = tmp_path / "prog.py"
    script.write_text(textwrap.dedent(program))
    try:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "scalene",
                "run",
                *options,
                "-o",
                str(tmp_path / "profile.json"),
                str(script),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the program hung under Scalene ({' '.join(options)})")


WAIT_FOR_OWN_ALARM = """
    import os, select, signal

    r, w = os.pipe()
    signal.signal(signal.SIGALRM, lambda *_: os.write(w, b"x"))
    poller = select.poll()
    poller.register(r, select.POLLIN)
    for i in range(10):
        signal.setitimer(signal.ITIMER_REAL, 0.05)
        if i % 2:
            select.select([r], [], [])  # no timeout: only the alarm ends it
        else:
            poller.poll()
        os.read(r, 1)
    print("done")
"""


@pytest.mark.parametrize("options", [(), ("--cpu-only",)], ids=["memory", "cpu-only"])
def test_wait_for_own_alarm(tmp_path: Path, options: tuple) -> None:
    # With memory profiling, libscalene's EINTR interposer is loaded.
    r = _scalene(tmp_path, WAIT_FOR_OWN_ALARM, *options)
    assert r.returncode == 0, r.stderr
    assert "done" in r.stdout


def test_signal_just_before_a_wait_is_not_lost(tmp_path: Path, helper: Path) -> None:
    r = _scalene(
        tmp_path,
        f"""
        import ctypes
        lib = ctypes.CDLL({str(helper)!r})
        lib.spin_then_pause.argtypes = [ctypes.c_double]
        for _ in range(3):
            lib.spin_then_pause(0.2)  # Scalene samples every 10 ms
        print("done")
        """,
        "--cpu-only",
    )
    assert r.returncode == 0, r.stderr
    assert "done" in r.stdout


def test_reload_is_not_another_sample(helper: Path) -> None:
    """A SIGALRM while the sample is pending only wakes the program."""
    import ctypes

    from scalene.scalene_utility import (
        consume_cpu_signal_arrival,
        install_cpu_signal_timestamper,
        set_cpu_signal_rearm_interval,
    )

    lib = ctypes.CDLL(str(helper))
    lib.spin.argtypes = [ctypes.c_double]
    old = _signal.signal(signal.SIGALRM, lambda *_: None)
    try:
        if not install_cpu_signal_timestamper(signal.SIGALRM):
            pytest.skip("C signal handler unavailable")
        set_cpu_signal_rearm_interval(0)  # no CPU-time arrivals here
        consume_cpu_signal_arrival()
        # Fires every 5 ms throughout 300 ms of C code.
        _signal.setitimer(signal.ITIMER_REAL, 0.005, 0.005)
        lib.spin(0.3)
        _signal.setitimer(signal.ITIMER_REAL, 0)
        arrival = consume_cpu_signal_arrival()
    finally:
        _signal.setitimer(signal.ITIMER_REAL, 0)
        _signal.signal(signal.SIGALRM, old if old is not None else _signal.SIG_DFL)
    assert arrival is not None
    assert len(arrival[2]) == 1


def test_wall_clock_timer_reloads_until_rearmed() -> None:
    from scalene.scalene_signal_manager import (
        CPU_TIMER_BACKUP_INTERVAL,
        ScaleneSignalManager,
    )

    manager = ScaleneSignalManager()
    manager._ScaleneSignalManager__orig_setitimer = _signal.setitimer  # type: ignore[attr-defined]
    old = _signal.signal(signal.SIGALRM, _signal.SIG_IGN)
    try:
        manager.get_signals().set_timer_signals(use_virtual_time=False)
        manager.restart_timer(100.0)
        value, interval = _signal.getitimer(signal.ITIMER_REAL)
        assert 99 < value <= 100
        assert interval == pytest.approx(CPU_TIMER_BACKUP_INTERVAL)

        # CPU-time mode: one-shot, as before (the C handler re-arms it).
        manager.get_signals().set_timer_signals(use_virtual_time=True)
        manager.restart_timer(100.0)
        assert _signal.getitimer(signal.ITIMER_VIRTUAL)[1] == 0
    finally:
        _signal.setitimer(signal.ITIMER_REAL, 0)
        _signal.setitimer(signal.ITIMER_VIRTUAL, 0)
        _signal.signal(signal.SIGALRM, old if old is not None else _signal.SIG_DFL)
