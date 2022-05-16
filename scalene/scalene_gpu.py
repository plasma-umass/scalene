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
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            self.__has_gpu = True
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            for i in range(self.__ngpus):
                self.__handle.append(pynvml.nvmlDeviceGetHandleByIndex(i))

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
            total_load = 0.0
            mem_used = 0
            for i in range(self.__ngpus):
                with contextlib.suppress(Exception):
                    total_load += pynvml.nvmlDeviceGetUtilizationRates(
                        self.__handle[i]
                    ).gpu
                    #mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.__handle[i])
                    #mem_used += mem_info.used
            total_load = (total_load / self.__ngpus) / 100.0
            mem_used = self.gpu_memory_usage(self.__pid)
            print (total_load, mem_used)
            return (total_load, mem_used)
        return (0.0, 0.0)
