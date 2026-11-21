import contextlib
import os
import sys
import time
from typing import List, Tuple

import pynvml

from scalene.scalene_accelerator import ScaleneAccelerator

MAX_UTILIZATION = 100.0

# NVML takes a per-process utilization sample every 1/6 s to 1 s, but Scalene
# asks on every CPU sample (~10 ms). Query at most this often (seconds).
UTILIZATION_QUERY_INTERVAL = 0.1

# NVIDIA documents that idle processes get no samples, so a missing sample can
# mean "idle". Once no new sample has arrived for this long (seconds), report 0
# rather than holding the last value forever.
UTILIZATION_STALE_AFTER = 2.0


class ScaleneNVIDIAGPU(ScaleneAccelerator):
    """A wrapper around the nvidia device driver library (pynvml)."""

    def __init__(self) -> None:
        self.__ngpus = 0
        self.__has_gpu = False
        self.__gpu_device = ""
        self.__pid = os.getpid()
        self.__has_per_pid_accounting = False
        self.__last_ts: List[int] = []
        self.__last_util: List[float] = []
        self.__last_sample_time: List[float] = []
        self.__proc_util_supported: List[bool] = []
        self.__last_query_time = 0.0
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            # Try to actually get utilization and memory usage.
            # If this fails, we disable GPU profiling.
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            self.__handle = [
                pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(self.__ngpus)
            ]
            self._reset_utilization_samples()
            self.__has_per_pid_accounting = self._set_accounting_mode()
            self.gpu_utilization(self.__pid)
            self.gpu_memory_usage(self.__pid)
            # If we make it this far, everything is working, so we can profile GPU usage.
            # Handle the case when GPUs are disabled. See https://github.com/plasma-umass/scalene/issues/536.
            self.__has_gpu = self.__ngpus > 0
            self.__gpu_device = "GPU"

    # def disable(self) -> None:
    #    """Turn off GPU accounting."""
    #    self.__has_gpu = False

    def __del__(self) -> None:
        if self.has_gpu() and not self.__has_per_pid_accounting:
            print(
                "NOTE: The GPU is currently running in a mode that can reduce Scalene's accuracy when reporting GPU utilization.",
                file=sys.stderr,
            )
            print(
                "If you have sudo privileges, you can run this command (Linux only) to enable per-process GPU accounting:",
                file=sys.stderr,
            )
            print("  python3 -m scalene.set_nvidia_gpu_modes", file=sys.stderr)

    def _set_accounting_mode(self) -> bool:
        """Returns true iff the accounting mode was set already for all GPUs or is now set."""
        ngpus = self.__ngpus

        for i in range(ngpus):
            # Check if each GPU has accounting mode set.
            h = self.__handle[i]
            if pynvml.nvmlDeviceGetAccountingMode(h) != pynvml.NVML_FEATURE_ENABLED:
                # If not, try to set it. As a side effect, we turn persistence mode on
                # so the driver is not unloaded (which undoes the accounting mode setting).
                try:
                    pynvml.nvmlDeviceSetPersistenceMode(h, pynvml.NVML_FEATURE_ENABLED)
                    pynvml.nvmlDeviceSetAccountingMode(h, pynvml.NVML_FEATURE_ENABLED)
                except pynvml.NVMLError:
                    # We don't have sufficient permissions.
                    return False

        return True

    def gpu_utilization(self, pid: int) -> float:
        """Return overall GPU utilization by pid if possible.
        Otherwise, returns aggregate utilization across all running processes.
        """
        if not self.has_gpu():
            return 0
        ngpus = self.__ngpus
        accounting_on = self.__has_per_pid_accounting
        utilization = 0.0
        now = time.monotonic()
        query = now - self.__last_query_time >= UTILIZATION_QUERY_INTERVAL
        if accounting_on and query:
            self.__last_query_time = now
        for i in range(ngpus):
            h = self.__handle[i]
            if accounting_on and self.__proc_util_supported[i]:
                if query:
                    self._read_process_utilization(i, h, pid, now)
                if now - self.__last_sample_time[i] > UTILIZATION_STALE_AFTER:
                    self.__last_util[i] = 0.0
                utilization += self.__last_util[i]
            elif accounting_on:
                # Per-process sampling is unsupported (e.g., MIG): fall back to
                # the lifetime average, which is better than nothing.
                with contextlib.suppress(Exception):
                    utilization += pynvml.nvmlDeviceGetAccountingStats(
                        h, pid
                    ).gpuUtilization
            else:
                with contextlib.suppress(pynvml.NVMLError):
                    # Silently ignore NVML errors. "Fixes" https://github.com/plasma-umass/scalene/issues/471.
                    utilization += pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        return (utilization / ngpus) / MAX_UTILIZATION

    def has_gpu(self) -> bool:
        """True iff the system has a detected GPU."""
        return self.__has_gpu

    def gpu_device(self) -> str:
        return self.__gpu_device

    def reinit(self) -> None:
        """Reinitialize the nvidia wrapper."""
        if not self.has_gpu():
            return
        self.__handle = []
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            self.__handle.extend(
                pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(self.__ngpus)
            )
            self._reset_utilization_samples()

    def _reset_utilization_samples(self) -> None:
        """Start reading per-process utilization samples afresh on every GPU."""
        self.__last_ts = [0] * self.__ngpus
        self.__last_util = [0.0] * self.__ngpus
        self.__last_sample_time = [0.0] * self.__ngpus
        self.__proc_util_supported = [True] * self.__ngpus
        self.__last_query_time = 0.0

    def _read_process_utilization(
        self, i: int, h: object, pid: int, now: float
    ) -> None:
        """Update GPU i's load for pid from any new NVML samples.

        Keeps the previous load when there is no new sample (NOT_FOUND).
        """
        try:
            samples = pynvml.nvmlDeviceGetProcessUtilization(h, self.__last_ts[i])
        except pynvml.NVMLError_NotSupported:
            self.__proc_util_supported[i] = False
            return
        except Exception:
            return
        if not samples:
            return
        self.__last_ts[i] = max(s.timeStamp for s in samples)
        self.__last_sample_time[i] = now
        # Use only the newest sample: the first read after startup returns
        # NVML's whole buffer, and averaging it would report stale history.
        mine = [s for s in samples if s.pid == pid]
        if mine:
            latest = max(mine, key=lambda s: s.timeStamp)
            self.__last_util[i] = min(float(latest.smUtil), MAX_UTILIZATION)
        else:
            # NVML sampled the GPU and this process wasn't on it.
            self.__last_util[i] = 0.0

    def gpu_memory_usage(self, pid: int) -> float:
        """Returns GPU memory used by the process pid, in MB."""
        # Adapted from https://github.com/gpuopenanalytics/pynvml/issues/21#issuecomment-678808658
        if not self.has_gpu():
            return 0
        total_used_GPU_memory = 0
        for i in range(self.__ngpus):
            handle = self.__handle[i]
            with contextlib.suppress(Exception):
                for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
                    # Only accumulate memory stats for the current pid.
                    if proc.usedGpuMemory and proc.pid == pid:
                        # First check is to protect against return of None
                        # from incompatible NVIDIA drivers.
                        total_used_GPU_memory += proc.usedGpuMemory / 1048576
        return total_used_GPU_memory

    def get_num_cores(self) -> int:
        return self.__ngpus

    def get_stats(self) -> Tuple[float, float]:
        """Returns a tuple of (utilization %, memory in use)."""
        if self.has_gpu():
            total_load = self.gpu_utilization(self.__pid)
            mem_used = self.gpu_memory_usage(self.__pid)
            return (total_load, mem_used)
        return (0.0, 0.0)
