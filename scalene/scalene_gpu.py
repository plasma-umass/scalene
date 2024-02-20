import contextlib
import os
import sys
from typing import Tuple

import pynvml


class ScaleneGPU:
    """A wrapper around the nvidia device driver library (pynvml)."""

    def __init__(self) -> None:
        self.__ngpus = 0
        self.__has_gpu = False
        self.__pid = os.getpid()
        self.__has_per_pid_accounting = False
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            # Try to actually get utilization and memory usage.
            # If this fails, we disable GPU profiling.
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            self.__handle = [
                pynvml.nvmlDeviceGetHandleByIndex(i)
                for i in range(self.__ngpus)
            ]
            self.__has_per_pid_accounting = self._set_accounting_mode()
            self.gpu_utilization(self.__pid)
            self.gpu_memory_usage(self.__pid)
            # If we make it this far, everything is working, so we can profile GPU usage.
            # Handle the case when GPUs are disabled. See https://github.com/plasma-umass/scalene/issues/536.
            self.__has_gpu = self.__ngpus > 0

    def disable(self) -> None:
        """Turn off GPU accounting."""
        self.__has_gpu = False

    def __del__(self) -> None:
        if self.has_gpu() and not self.__has_per_pid_accounting:
            print(
                "NOTE: The GPU is currently running in a mode that can reduce Scalene's accuracy when reporting GPU utilization.",
                file=sys.stderr
            )
            print(
                "Run once as Administrator or root (i.e., prefixed with `sudo`) to enable per-process GPU accounting.",
                file=sys.stderr
            )

    def _set_accounting_mode(self) -> bool:
        """Returns true iff the accounting mode was set already for all GPUs or is now set."""
        ngpus = self.__ngpus

        for i in range(ngpus):
            # Check if each GPU has accounting mode set.
            h = self.__handle[i]
            if (
                pynvml.nvmlDeviceGetAccountingMode(h)
                != pynvml.NVML_FEATURE_ENABLED
            ):
                # If not, try to set it. As a side effect, we turn persistence mode on
                # so the driver is not unloaded (which undoes the accounting mode setting).
                try:
                    pynvml.nvmlDeviceSetPersistenceMode(
                        h, pynvml.NVML_FEATURE_ENABLED
                    )
                    pynvml.nvmlDeviceSetAccountingMode(
                        h, pynvml.NVML_FEATURE_ENABLED
                    )
                except pynvml.NVMLError:
                    # We don't have sufficient permissions.
                    return False

        return True

    def gpu_utilization(self, pid: int) -> float:
        """Return overall GPU utilization by pid if possible.
        Otherwise, returns aggregate utilization across all running processes."""
        if not self.has_gpu():
            return 0
        ngpus = self.__ngpus
        accounting_on = self.__has_per_pid_accounting
        utilization = 0
        for i in range(ngpus):
            h = self.__handle[i]
            if accounting_on:
                with contextlib.suppress(Exception):
                    utilization += pynvml.nvmlDeviceGetAccountingStats(
                        h, pid
                    ).gpuUtilization
            else:
                try:
                    utilization += pynvml.nvmlDeviceGetUtilizationRates(h).gpu
                except pynvml.nvml.NVMLError_Unknown:
                    # Silently ignore NVML errors. "Fixes" https://github.com/plasma-umass/scalene/issues/471.
                    pass
        return (utilization / ngpus) / 100.0

    def has_gpu(self) -> bool:
        """True iff the system has a detected GPU."""
        return self.__has_gpu

    def nvml_reinit(self) -> None:
        """Reinitialize the nvidia wrapper."""
        if not self.has_gpu():
            return
        self.__handle = []
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            self.__handle.extend(
                pynvml.nvmlDeviceGetHandleByIndex(i)
                for i in range(self.__ngpus)
            )

    def gpu_memory_usage(self, pid: int) -> float:
        """Returns GPU memory used by the process pid, in MB."""
        # Adapted from https://github.com/gpuopenanalytics/pynvml/issues/21#issuecomment-678808658
        if not self.has_gpu():
            return 0
        total_used_GPU_memory = 0
        for i in range(self.__ngpus):
            handle = self.__handle[i]
            with contextlib.suppress(Exception):
                for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(
                    handle
                ):
                    # Only accumulate memory stats for the current pid.
                    if proc.usedGpuMemory and proc.pid == pid:
                        # First check is to protect against return of None
                        # from incompatible NVIDIA drivers.
                        total_used_GPU_memory += proc.usedGpuMemory / 1048576
        return total_used_GPU_memory

    def get_stats(self) -> Tuple[float, float]:
        """Returns a tuple of (utilization %, memory in use)."""
        if self.has_gpu():
            total_load = self.gpu_utilization(self.__pid)
            mem_used = self.gpu_memory_usage(self.__pid)
            return (total_load, mem_used)
        return (0.0, 0.0)
