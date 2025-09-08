from abc import ABC, abstractmethod
from typing import Tuple


# Base class for accelerators (GPUs, TPUs, etc.)
class ScaleneAccelerator(ABC):

    @abstractmethod
    def has_gpu(self) -> bool:
        pass

    @abstractmethod
    def gpu_device(self) -> str:
        pass

    @abstractmethod
    def reinit(self) -> None:
        pass

    @abstractmethod
    def get_stats(self) -> Tuple[float, float]:
        pass

    @abstractmethod
    def get_num_cores(self) -> int:
        pass
