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
        # with contextlib.suppress(Exception):
        pynvml.nvmlInit()
        self.__has_gpu = True
        self.__ngpus = pynvml.nvmlDeviceGetCount()
        for i in range(self.__ngpus):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            self.__handle.append(handle)
        self.__has_per_pid_accounting = self.set_accounting_mode()

    def __del__(self) -> None:
        if not self.__has_per_pid_accounting:
            print("NOTE: The GPU is currently running in a mode that reduces Scalene's accuracy when reporting GPU utilization.")
            print("Run once as root (i.e., prefixed with `sudo`) to enable per-process GPU accounting.")
        
    def set_accounting_mode(self) -> bool:
        """Returns true iff the accounting mode was set already for all GPUs or is now set."""
        ngpus = pynvml.nvmlDeviceGetCount()

        for i in range(ngpus):
            # Check if each GPU has accounting mode set.
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            if pynvml.nvmlDeviceGetAccountingMode(h) != pynvml.NVML_FEATURE_ENABLED:
                # If not, try to set it.
                try:
                    pynvml.nvmlDeviceSetAccountingMode(h, pynvml.NVML_FEATURE_ENABLED)
                except pynvml.NVMLError:
                    # We don't have sufficient permissions.
                    return False
                    pass

        return True

    def gpu_utilization(self, pid) -> float:
        """Return overall GPU utilization by pid if possible.

        Otherwise, returns aggregate utilization across all running processes."""
        ngpus = pynvml.nvmlDeviceGetCount()
        accounting_on = self.__has_per_pid_accounting
        utilization = 0
        for i in range(ngpus):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            if accounting_on:
                try:
                    utilization += pynvml.nvmlDeviceGetAccountingStats(h, pid).gpuUtilization
                except:
                    pass
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
            for i in range(self.__ngpus):
                self.__handle.append(pynvml.nvmlDeviceGetHandleByIndex(i))

    def gpu_memory_usage(self, pid) -> float:
        """Returns GPU memory used by the process pid, in MB."""
        # Adapted from https://github.com/gpuopenanalytics/pynvml/issues/21#issuecomment-678808658
        total_used_GPU_memory = 0
        for dev_id in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(dev_id)
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
