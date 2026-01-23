# Simplified running statistics - only computes mean and peak
# (variance/skewness/kurtosis removed as they were unused)


class RunningStats:
    """Incrementally compute mean and peak statistics using Welford's algorithm."""

    __slots__ = ("_n", "_m1", "_peak")

    def __init__(self) -> None:
        self._n: int = 0
        self._m1: float = 0.0
        self._peak: float = 0.0

    def __add__(self: "RunningStats", other: "RunningStats") -> "RunningStats":
        s = RunningStats()
        if other._n > 0:
            total_n = self._n + other._n
            s._m1 = (self._m1 * self._n + other._m1 * other._n) / total_n
            s._n = total_n
            s._peak = max(self._peak, other._peak)
        else:
            s._n = self._n
            s._m1 = self._m1
            s._peak = self._peak
        return s

    def clear(self) -> None:
        """Reset for new samples."""
        self._n = 0
        self._m1 = 0.0
        self._peak = 0.0

    def push(self, x: float) -> None:
        """Add a sample using Welford's online algorithm for mean."""
        if x > self._peak:
            self._peak = x
        self._n += 1
        # Welford's algorithm: mean += (x - mean) / n
        self._m1 += (x - self._m1) / self._n

    def peak(self) -> float:
        """The maximum sample seen."""
        return self._peak

    def size(self) -> int:
        """The number of samples."""
        return self._n

    def mean(self) -> float:
        """Arithmetic mean (average)."""
        return self._m1
