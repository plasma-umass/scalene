"""HyperLogLog cardinality estimator.

Used by ``ScaleneStatistics`` alongside the Space-Saving heavy-hitter
table (``combined_stacks``) to report an unbiased estimate of how many
distinct stitched stacks the profiler ever saw, including any that were
evicted from the table. The Space-Saving table answers "which stacks
matter"; HyperLogLog answers "how many were there in total".

Standard HLL (Flajolet, Fusy, Gandouet, Meunier 2007). Single-process,
non-cryptographic — appropriate for an in-memory statistics counter, not
for adversarial inputs.

With ``p = 12`` (the default), this uses 4 KB of memory and gives a
standard error of about 1.04 / sqrt(2**12) ≈ 1.6%. Mergeable across
subprocesses via register-wise max.
"""

from __future__ import annotations

import math
from typing import Any


def _mix64(x: int) -> int:
    """SplitMix64 finalizer. Python's built-in hash() is fine for dicts
    but isn't a uniform random function — some bit positions are
    correlated for nearby tuples. Running the result through SplitMix's
    avalanche step gives the bit-mixing HLL needs without the overhead
    of a cryptographic digest or a third-party hash library.
    """
    x &= 0xFFFFFFFFFFFFFFFF
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (x ^ (x >> 31)) & 0xFFFFFFFFFFFFFFFF


class HyperLogLog:
    """Probabilistic distinct-element counter.

    Memory: 2**p bytes (each register holds the max leading-zero run of
    any hash that landed in it, fits in one byte for any p ≤ 58).
    Accuracy: standard error ≈ 1.04 / sqrt(2**p).
    """

    __slots__ = ("p", "m", "alpha", "registers")

    def __init__(self, p: int = 12) -> None:
        if not (4 <= p <= 18):
            raise ValueError(f"HyperLogLog precision p must be in [4, 18], got {p}")
        self.p = p
        self.m = 1 << p
        self.alpha = self._alpha(self.m)
        self.registers = bytearray(self.m)

    def add(self, item: Any) -> None:
        """Record one observation of ``item``. Idempotent up to register
        max: adding the same item twice doesn't change the estimate."""
        h = _mix64(hash(item))
        idx = h & (self.m - 1)
        w = h >> self.p
        # Rank = position of the leftmost 1 in w (1-indexed). If w is 0,
        # treat as if all (64 - p) remaining bits are zero. Otherwise
        # use bit_length to locate the most significant set bit.
        bits = 64 - self.p
        rank = bits + 1 if w == 0 else bits - w.bit_length() + 1
        if rank > self.registers[idx]:
            self.registers[idx] = rank

    def cardinality(self) -> int:
        """Return the estimated number of distinct items added."""
        # Raw harmonic-mean estimate.
        z = sum(2.0**-r for r in self.registers)
        e = self.alpha * self.m * self.m / z
        # Small-range correction: linear counting when many registers
        # are still zero — much more accurate at low cardinality.
        if e <= 2.5 * self.m:
            v = sum(1 for r in self.registers if r == 0)
            if v > 0:
                e = self.m * math.log(self.m / v)
        # 64-bit hash means we never hit the original HLL's
        # large-range correction (kicks in only above 2**32 / 30).
        return int(e + 0.5)

    def merge(self, other: HyperLogLog) -> None:
        """In-place register-wise max. Used to combine HLLs collected
        in separate subprocesses (or threads) without losing accuracy."""
        if self.m != other.m:
            raise ValueError(
                f"cannot merge HLLs with different precision: " f"{self.p} vs {other.p}"
            )
        for i in range(self.m):
            if other.registers[i] > self.registers[i]:
                self.registers[i] = other.registers[i]

    def clear(self) -> None:
        """Reset all registers to zero."""
        # bytearray.__init__ is faster than zeroing in a loop.
        self.registers = bytearray(self.m)

    @staticmethod
    def _alpha(m: int) -> float:
        # Bias-correction constants from the original HLL paper.
        if m == 16:
            return 0.673
        if m == 32:
            return 0.697
        if m == 64:
            return 0.709
        return 0.7213 / (1 + 1.079 / m)
