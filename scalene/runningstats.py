# Translated from C++ by Emery Berger from https://www.johndcook.com/blog/skewness_kurtosis/

import math


class RunningStats:
    """Incrementally compute statistics"""

    def __init__(self) -> None:
        self.clear()

    def __add__(self: "RunningStats", other: "RunningStats") -> "RunningStats":
        s = RunningStats()
        if other._n > 0:
            s._m1 = (self._m1 * self._n + other._m1 * other._n) / (
                self._n + other._n
            )
            # TBD: Fix s._m2 and friends
            # For now, leave at zero.
            s._n = self._n + other._n
            s._peak = max(self._peak, other._peak)
        else:
            s = self
        return s

    def clear(self) -> None:
        """Reset for new samples"""
        self._n = 0
        self._m1 = self._m2 = self._m3 = self._m4 = 0.0
        self._peak = 0.0

    def push(self, x: float) -> None:
        """Add a sample"""
        if x > self._peak:
            self._peak = x
        n1 = self._n
        self._n += 1
        delta = x - self._m1
        delta_n = delta / self._n
        delta_n2 = delta_n * delta_n
        term1 = delta * delta_n * n1
        self._m1 += delta_n
        self._m4 += (
            term1 * delta_n2 * (self._n * self._n - 3 * self._n + 3)
            + 6 * delta_n2 * self._m2
            - 4 * delta_n * self._m3
        )
        self._m3 += term1 * delta_n * (self._n - 2) - 3 * delta_n * self._m2
        self._m2 += term1

    def peak(self) -> float:
        """The maximum sample seen."""
        return self._peak

    def size(self) -> int:
        """The number of samples"""
        return self._n

    def mean(self) -> float:
        """Arithmetic mean, a.k.a. average"""
        return self._m1

    def var(self) -> float:
        """Variance"""
        return self._m2 / (self._n - 1.0)

    def std(self) -> float:
        """Standard deviation"""
        return math.sqrt(self.var())

    def sem(self) -> float:
        """Standard error of the mean"""
        return self.std() / math.sqrt(self._n)
