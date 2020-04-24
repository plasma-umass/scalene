import math
import random
from typing import List


class adaptive:
    """Implements sampling to achieve the effect of a uniform random sample."""

    sample_array: List[float] = []
    current_index = 0
    total_samples = 0
    max_samples = 0
    count_average = 0
    sum_average = 0
    max_average = 1

    def __init__(self, size: int):
        self.max_samples = size
        # must be a power of two
        self.sample_array = [0] * size

    def add(self, value: float) -> None:
        if self.current_index >= self.max_samples:
            # Decimate
            # print("DECIMATION " + str(self.sample_array))
            new_array = [0.0] * self.max_samples
            for i in range(0, self.max_samples // 3):
                arr = [self.sample_array[i * 3 + j] for j in range(0, 3)]
                arr.sort()
                new_array[i] = arr[1]  # Median
            self.current_index = self.max_samples // 3
            self.sample_array = new_array
            # print("POST DECIMATION = " + str(self.sample_array))
            # Update average length
            self.max_average *= 3
        self.sample_array[self.current_index] = value
        self.current_index += 1  # count_average += 1

    def get(self) -> List[float]:
        return self.sample_array

    def len(self) -> int:
        return self.current_index
