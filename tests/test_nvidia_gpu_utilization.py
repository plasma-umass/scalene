"""On NVIDIA GPUs, the GPU load charged to a line must be the load right now.

In accounting mode, Scalene read nvmlDeviceGetAccountingStats().gpuUtilization,
which NVIDIA defines as an average over the whole life of the process. Every
line got that slowly moving average, so lines that kept the GPU busy and lines
that never used it showed about the same GPU percent. Scalene now reads this
process's latest sample from nvmlDeviceGetProcessUtilization(). NVML takes a
sample about once a second and says NOT_FOUND until the next one, while
Scalene asks on every CPU sample (about every 10 ms).

Why this call: it is the only NVML call that is both per process and current.
nvmlDeviceGetUtilizationRates() is current but counts every process on the
GPU; GPM is whole-GPU and Hopper-only; CUPTI would be exact but is a much
bigger change. Limits: about 1 s resolution; not supported on MIG; in Docker,
NVML reports host PIDs, so Scalene's own PID never matches. NVIDIA's docs say
idle processes get no samples, but the driver we measured sent 0% samples
every second, so the last value is kept on NOT_FOUND -- but only for a
couple of seconds, so a driver that follows the docs doesn't leave a stale
load stuck. NVML is queried at most every 0.1 s, and GPUs that don't support
per-process sampling (e.g., MIG) fall back to the accounting-stats average.
"""

from __future__ import annotations

import importlib
import itertools
import os
import sys
from types import SimpleNamespace

import pytest

ME = os.getpid()  # ScaleneNVIDIAGPU asks about its own process
OTHER = ME + 1
NOT_FOUND = "NOT_FOUND"  # no sample newer than the last one read
NOT_SUPPORTED = "NOT_SUPPORTED"  # e.g., MIG

_timestamps = itertools.count(1_000_000, 1_000_000)  # one per second, in us


def sample(pid, sm_util):
    return SimpleNamespace(pid=pid, smUtil=sm_util, timeStamp=next(_timestamps))


class MockNVML:
    """Just enough of pynvml for ScaleneNVIDIAGPU: one GPU, accounting on."""

    NVML_FEATURE_ENABLED = 1

    class NVMLError(Exception):
        pass

    class NVMLError_NotFound(NVMLError):
        pass

    class NVMLError_NotSupported(NVMLError):
        pass

    def __init__(self):
        self.replies = []  # one per nvmlDeviceGetProcessUtilization() call
        self.queries = 0

    def nvmlInit(self): return None
    def nvmlDeviceGetCount(self): return 1
    def nvmlDeviceGetHandleByIndex(self, i): return i
    def nvmlDeviceGetAccountingMode(self, handle): return self.NVML_FEATURE_ENABLED
    def nvmlDeviceGetComputeRunningProcesses(self, handle): return []

    def nvmlDeviceGetAccountingStats(self, handle, pid):
        return SimpleNamespace(gpuUtilization=50)  # the lifetime average

    def nvmlDeviceGetProcessUtilization(self, handle, last_seen):
        self.queries += 1
        reply = self.replies.pop(0)
        if reply == NOT_FOUND:
            raise self.NVMLError_NotFound()
        if reply == NOT_SUPPORTED:
            raise self.NVMLError_NotSupported()
        return reply


class Clock:
    """A fake time.monotonic() that only moves when told to."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


MODULE = "scalene.scalene_nvidia_gpu"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def nvml(monkeypatch, clock):
    mock_nvml = MockNVML()
    was_imported = MODULE in sys.modules
    monkeypatch.setitem(sys.modules, "pynvml", mock_nvml)  # not installed on macOS
    module = importlib.import_module(MODULE)
    monkeypatch.setattr(module, "pynvml", mock_nvml)
    monkeypatch.setattr(module, "time", clock)
    yield mock_nvml
    if not was_imported:
        # Don't leave a copy bound to the mock for later tests to import.
        sys.modules.pop(MODULE, None)


@pytest.fixture
def gpu(nvml):
    return sys.modules[MODULE].ScaleneNVIDIAGPU()


def loads(gpu, clock, n, step=0.25):
    """The GPU load of the next n CPU samples, step seconds apart."""
    result = []
    for _ in range(n):
        result.append(gpu.get_stats()[0])
        clock.now += step
    return result


def test_load_is_the_latest_sample(nvml, gpu, clock):
    nvml.replies = [[sample(ME, 90)], [sample(ME, 0)]]
    assert loads(gpu, clock, 2) == pytest.approx([0.9, 0.0])


def test_load_is_kept_until_the_next_sample(nvml, gpu, clock):
    nvml.replies = [[sample(ME, 90)], NOT_FOUND, NOT_FOUND]
    assert loads(gpu, clock, 3) == pytest.approx([0.9, 0.9, 0.9])


def test_other_processes_do_not_count(nvml, gpu, clock):
    nvml.replies = [[sample(OTHER, 80)]]
    assert loads(gpu, clock, 1) == pytest.approx([0.0])


def test_load_goes_to_zero_once_samples_stop(nvml, gpu, clock):
    # NVIDIA's docs say idle processes get no samples at all.
    nvml.replies = [[sample(ME, 90)]] + [NOT_FOUND] * 4
    assert loads(gpu, clock, 5, step=1.0) == pytest.approx([0.9, 0.9, 0.9, 0.0, 0.0])


def test_newest_sample_wins_over_buffered_history(nvml, gpu, clock):
    # The first read returns NVML's whole buffer; only the newest sample counts.
    nvml.replies = [[sample(ME, 100), sample(ME, 100), sample(ME, 10)]]
    assert loads(gpu, clock, 1) == pytest.approx([0.1])


def test_nvml_is_not_queried_on_every_cpu_sample(nvml, gpu, clock):
    nvml.replies = [[sample(ME, 50)], [sample(ME, 70)]]
    assert loads(gpu, clock, 10, step=0.01) == pytest.approx([0.5] * 10)
    assert nvml.queries == 1
    clock.now += 0.1
    assert loads(gpu, clock, 1) == pytest.approx([0.7])
    assert nvml.queries == 2


def test_falls_back_to_accounting_stats_when_unsupported(nvml, gpu, clock):
    # e.g., MIG: per-process sampling is unsupported, so use the lifetime average.
    nvml.replies = [NOT_SUPPORTED]
    assert loads(gpu, clock, 3) == pytest.approx([0.0, 0.5, 0.5])
    assert nvml.queries == 1
