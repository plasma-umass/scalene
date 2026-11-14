"""Windows CPU sampling via the native timer thread (start_cpu_timer_thread).

Windows has no timer signals. A native thread that never takes the GIL trips
Scalene's CPU signal every interval, so CPython runs the Python handler on
the main thread at its next safe point, as on Unix; the delay from the tick
to the handler (consume_cpu_signal_arrival) separates Python from native
time, including C code that holds the GIL (`big + big`), which a Python
sampler thread can't see.
"""

import os
import subprocess
import sys
import textwrap

import pytest

from scalene.scalene_utility import (
    native_cpu_timer_available,
    set_native_cpu_timer_interval,
    start_native_cpu_timer,
    stop_native_cpu_timer,
)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows stub")
def test_native_cpu_timer_is_windows_only() -> None:
    assert not native_cpu_timer_available()
    assert start_native_cpu_timer(15, 0.01) is False
    set_native_cpu_timer_interval(0.01)  # no-ops, no exceptions
    stop_native_cpu_timer()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only timer thread")
def test_native_cpu_timer_runs_handler_on_main_thread_and_measures_deferral() -> (
    None
):
    # In a fresh interpreter: importing scalene_profiler (as other tests do)
    # reroutes signal.signal() through its replacement shims.
    script = textwrap.dedent("""
        import signal, sys, threading, time
        from scalene.scalene_cpu_profiler import NATIVE_DEFERRAL_THRESHOLD
        from scalene.scalene_utility import (
            consume_cpu_signal_arrival,
            native_cpu_timer_available,
            start_native_cpu_timer,
            stop_native_cpu_timer,
        )
        if not native_cpu_timer_available():
            print("SKIP")
            sys.exit(0)
        deferrals = []
        threads = set()
        def handler(signum, frame):
            threads.add(threading.current_thread() is threading.main_thread())
            arrival = consume_cpu_signal_arrival()
            if arrival is not None:
                deferrals.append(arrival[0])
        signal.signal(signal.SIGBREAK, handler)

        def measure(work):
            deferrals.clear()
            assert start_native_cpu_timer(int(signal.SIGBREAK), 0.005)
            end = time.perf_counter() + 0.6
            work(end)
            stop_native_cpu_timer()
            assert deferrals, "handler never ran"
            return sum(d > NATIVE_DEFERRAL_THRESHOLD for d in deferrals) / len(deferrals)

        def python_work(end):
            x = 0
            while time.perf_counter() < end:
                for i in range(1000):
                    x += i * i

        big = list(range(1_000_000))
        def operator_work(end):  # C code that holds the GIL, no call
            while time.perf_counter() < end:
                c = big + big

        py_native = measure(python_work)
        op_native = measure(operator_work)
        assert threads == {True}, threads
        print(f"OK python={py_native:.0%} operator={op_native:.0%} native")
        assert py_native < 0.2, py_native
        assert op_native > 0.8, op_native
    """)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCALENE")}
    out = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    if out.stdout.strip() == "SKIP":
        pytest.skip("native extension without the CPU timer thread")
    assert out.stdout.startswith("OK"), out.stdout + out.stderr
