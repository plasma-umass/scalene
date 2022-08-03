import contextlib
import os
from typing import Tuple

import pynvml


class ScaleneGPU:
    """A wrapper around the nvidia device driver library (pynvml)."""

    def __init__(self) -> None:
        self.__ngpus = 0
        self.__has_gpu = False
        self.__handle = []
        self.__pid = os.getpid()
        self.__has_per_pid_accounting = False
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            # If we make it here, we have an NVIDIA GPU.
            self.__has_gpu = True
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            for i in range(self.__ngpus):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                self.__handle.append(handle)
            self.__has_per_pid_accounting = self.set_accounting_mode()

    def __del__(self) -> None:
        if self.__has_gpu and not self.__has_per_pid_accounting:
            print(
                "NOTE: The GPU is currently running in a mode that can reduce Scalene's accuracy when reporting GPU utilization."
            )
            print(
                "Run once as root (i.e., prefixed with `sudo`) to enable per-process GPU accounting."
            )

    def set_accounting_mode(self) -> bool:
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
                utilization += pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        return (utilization / ngpus) / 100.0

    def has_gpu(self) -> bool:
        """True iff the system has a detected GPU."""
        return self.__has_gpu

    def nvml_reinit(self) -> None:
        """Reinitialize the nvidia wrapper."""
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
        total_used_GPU_memory = 0
        for i in range(self.__ngpus):
            handle = self.__handle[i]
            for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
                if proc.pid == pid:
                    total_used_GPU_memory += proc.usedGpuMemory / 1048576
        return total_used_GPU_memory

    def get_stats(self) -> Tuple[float, float]:
        """Returns a tuple of (utilization %, memory in use)."""
        if self.__has_gpu:
            total_load = self.gpu_utilization(self.__pid)
            mem_used = self.gpu_memory_usage(self.__pid)
            return (total_load, mem_used)
        return (0.0, 0.0)
