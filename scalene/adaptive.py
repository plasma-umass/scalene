from typing import List


class Adaptive:
    """Implements sampling to achieve the effect of a uniform random sample."""

    def __init__(self, size: int):
        # size must be a power of two
        self.max_samples = size
        self.current_index = 0
        self.sample_array = [0.0] * size

    def __add__(self: "Adaptive", other: "Adaptive") -> "Adaptive":
        n = Adaptive(self.max_samples)
        for i in range(0, self.max_samples):
            n.sample_array[i] = self.sample_array[i] + other.sample_array[i]
        n.current_index = max(self.current_index, other.current_index)
        return n

    def __iadd__(self: "Adaptive", other: "Adaptive") -> "Adaptive":
        for i in range(0, self.max_samples):
            self.sample_array[i] += other.sample_array[i]
        self.current_index = max(self.current_index, other.current_index)
        return self

    def add(self, value: float) -> None:
        if self.current_index >= self.max_samples:
            # Decimate
            new_array = [0.0] * self.max_samples
            for i in range(0, self.max_samples // 3):
                arr = [self.sample_array[i * 3 + j] for j in range(0, 3)]
                arr.sort()
                new_array[i] = arr[1]  # Median
            self.current_index = self.max_samples // 3
            self.sample_array = new_array
        self.sample_array[self.current_index] = value
        self.current_index += 1

    def get(self) -> List[float]:
        return self.sample_array

    def len(self) -> int:
        return self.current_index
