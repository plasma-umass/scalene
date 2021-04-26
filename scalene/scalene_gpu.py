import pynvml


class ScaleneGPU:
    """A wrapper around the nvidia device driver library (nvidia-ml-py)."""

    def __init__(self) -> None:
        self.__ngpus = 0
        self.__has_gpu = False
        self.__handle = []
        try:
            pynvml.nvmlInit()
            self.__has_gpu = True
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            for i in range(self.__ngpus):
                self.__handle.append(pynvml.nvmlDeviceGetHandleByIndex(i))
        except:
            pass

    def has_gpu(self) -> bool:
        return self.__has_gpu

    def nvml_reinit(self) -> None:
        self.__handle = []
        try:
            pynvml.nvmlInit()
            self.__ngpus = pynvml.nvmlDeviceGetCount()
            for i in range(self.__ngpus):
                self.__handle.append(pynvml.nvmlDeviceGetHandleByIndex(i))
        except:
            pass

    def load(self) -> float:
        if self.__has_gpu:
            l = 0.0
            for i in range(self.__ngpus):
                l += pynvml.nvmlDeviceGetUtilizationRates(self.__handle[i]).gpu
            return (l / self.__ngpus) / 100.0
        return 0.0

    def memory_used(self) -> int:
        mem_used = 0
        for i in range(self.__ngpus):
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.__handle[i])
            mem_used += mem_info.used
        return mem_used
