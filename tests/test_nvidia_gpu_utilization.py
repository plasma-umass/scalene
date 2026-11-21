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
every second, so keeping the last value on NOT_FOUND is right.
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

    def __init__(self):
        self.replies = []  # one per nvmlDeviceGetProcessUtilization() call

    def nvmlInit(self): return None
    def nvmlDeviceGetCount(self): return 1
    def nvmlDeviceGetHandleByIndex(self, i): return i
    def nvmlDeviceGetAccountingMode(self, handle): return self.NVML_FEATURE_ENABLED
    def nvmlDeviceGetComputeRunningProcesses(self, handle): return []

    def nvmlDeviceGetAccountingStats(self, handle, pid):
        return SimpleNamespace(gpuUtilization=50)  # the lifetime average

    def nvmlDeviceGetProcessUtilization(self, handle, last_seen):
        reply = self.replies.pop(0)
        if reply == NOT_FOUND:
            raise self.NVMLError_NotFound()
        return reply


@pytest.fixture
def nvml(monkeypatch):
    mock_nvml = MockNVML()
    monkeypatch.setitem(sys.modules, "pynvml", mock_nvml)  # not installed on macOS
    module = importlib.import_module("scalene.scalene_nvidia_gpu")
    monkeypatch.setattr(module, "pynvml", mock_nvml)
    return mock_nvml


@pytest.fixture
def gpu(nvml):
    from scalene.scalene_nvidia_gpu import ScaleneNVIDIAGPU

    return ScaleneNVIDIAGPU()


def loads(gpu, n):
    """The GPU load of the next n CPU samples."""
    return [gpu.get_stats()[0] for _ in range(n)]


def test_load_is_the_latest_sample(nvml, gpu):
    nvml.replies = [[sample(ME, 90)], [sample(ME, 0)]]
    assert loads(gpu, 2) == pytest.approx([0.9, 0.0])


def test_load_is_kept_until_the_next_sample(nvml, gpu):
    nvml.replies = [[sample(ME, 90)], NOT_FOUND, NOT_FOUND]
    assert loads(gpu, 3) == pytest.approx([0.9, 0.9, 0.9])


def test_other_processes_do_not_count(nvml, gpu):
    nvml.replies = [[sample(OTHER, 80)]]
    assert loads(gpu, 1) == pytest.approx([0.0])
