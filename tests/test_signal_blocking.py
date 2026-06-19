import os
import signal
from types import ModuleType

import pytest

from scalene.scalene_utility import patch_module_functions_with_signal_blocking


@pytest.mark.skipif(
    not hasattr(signal, "pthread_sigmask"), reason="POSIX-only signal masks"
)
def test_patch_module_functions_with_signal_blocking_blocks_selected_functions(
    monkeypatch,
):
    module = ModuleType("fake_pyodbc")
    call_log = []

    def connect(dsn: str) -> str:
        call_log.append(("connect", dsn))
        return "connected"

    def drivers() -> str:
        call_log.append(("drivers",))
        return "drivers"

    module.connect = connect
    module.drivers = drivers

    current_pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: current_pid)

    sigmask_calls = []

    def fake_pthread_sigmask(how: int, mask):
        sigmask_calls.append((how, tuple(mask)))
        if how == signal.SIG_BLOCK:
            return ("original-mask",)
        return ()

    monkeypatch.setattr(signal, "pthread_sigmask", fake_pthread_sigmask)

    patch_module_functions_with_signal_blocking(
        module,
        (signal.SIGALRM, signal.SIGPROF),
        function_names=("connect",),
    )

    assert module.connect("dsn") == "connected"
    assert module.drivers() == "drivers"

    assert call_log == [("connect", "dsn"), ("drivers",)]
    assert sigmask_calls == [
        (signal.SIG_BLOCK, (signal.SIGALRM, signal.SIGPROF)),
        (signal.SIG_SETMASK, ("original-mask",)),
    ]
