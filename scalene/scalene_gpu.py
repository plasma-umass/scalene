import contextlib
import pynvml

from typing import Tuple


class ScaleneGPU:
    """A wrapper around the nvidia device driver library (nvidia-ml-py)."""

    def __init__(self) -> None:
        self.__ngpus = 0
        self.__has_gpu = False
        self.__handle = []
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            self.__has_gpu = True
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            for i in range(self.__ngpus):
                self.__handle.append(pynvml.nvmlDeviceGetHandleByIndex(i))

    def has_gpu(self) -> bool:
        return self.__has_gpu

    def nvml_reinit(self) -> None:
        self.__handle = []
        with contextlib.suppress(Exception):
            pynvml.nvmlInit()
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            for i in range(self.__ngpus):
                self.__handle.append(pynvml.nvmlDeviceGetHandleByIndex(i))

    def get_stats(self) -> Tuple[float, float]:
        if self.__has_gpu:
            total_load = 0.0
            mem_used = 0
            for i in range(self.__ngpus):
                with contextlib.suppress(Exception):
                    total_load += pynvml.nvmlDeviceGetUtilizationRates(
                        self.__handle[i]
                    ).gpu
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.__handle[i])
                    mem_used += mem_info.used
            total_load = (total_load / self.__ngpus) / 100.0
            return (total_load, mem_used)
        else:
            return (0.0, 0.0)
