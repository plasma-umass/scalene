"""cpu_signal_handler must process a sample with the interval it was armed with.

_process_cpu_sample() splits a sample's CPU time into Python (the interval
the timer was armed with) and native (any excess). The handler used to start
with ``next_interval = Scalene._sample_cpu_interval()``, a fallback for its
``finally`` block, which overwrote ``__last_cpu_interval`` with a fresh
random draw before the sample was processed. The "expected" Python time was
then unrelated to the real interval, and about a third of pure-Python time
was reported as native.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from scalene.scalene_profiler import Scalene
from scalene.time_info import TimeInfo


def test_handler_uses_the_armed_interval():
    armed = 0.0123
    seen = []

    def fake_process(*_args, **_kwargs):
        seen.append(Scalene._Scalene__last_cpu_interval)  # type: ignore[attr-defined]

    prev = TimeInfo(virtual=1.0, wallclock=1.0, sys=0.0, user=1.0)
    args = SimpleNamespace(
        cpu_sampling_rate=0.01, stacks=False, async_profile=False
    )
    signal_manager = mock.MagicMock()
    with mock.patch.multiple(
        Scalene,
        _Scalene__last_cpu_interval=armed,
        _Scalene__last_signal_time=prev,
        _Scalene__args=args,
        _Scalene__accelerator=None,
        _Scalene__torch_profiler=None,
        _Scalene__signal_manager=signal_manager,
        _process_cpu_sample=staticmethod(fake_process),
        create=True,
    ), mock.patch(
        "scalene.scalene_profiler.compute_frames_to_record", return_value=[]
    ):
        Scalene.cpu_signal_handler(0, None)

    assert seen == [armed]
