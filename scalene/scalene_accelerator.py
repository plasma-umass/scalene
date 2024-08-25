from typing import Tuple
from abc import ABC, abstractmethod


# Base class for accelerators (GPUs, TPUs, etc.)
class ScaleneAccelerator(ABC):

    def has_gpu(self) -> bool:
        return False

    def gpu_device(self) -> str:
        return "None"

    def reinit(self) -> None:
        pass

    def get_stats(self) -> Tuple[float, float]:
        return (0.0, 0.0)

    def get_num_cores(self) -> int:
        return 0
