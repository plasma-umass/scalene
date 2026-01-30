import math
import random
import sys
from typing import Any, Callable, List

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class sorted_reservoir:
    """
    An implementation of reservoir sampling (Vitter) using the
    geometric distribution to avoid repeated calls to the RNG. The
    only access to the reservoir is a sorted list.
    """

    def __init__(self: Self, k: int, key: Callable[[Any], Any] = lambda a: a) -> None:
        """Initialize a reservoir of size k."""
        assert k > 0
        self.k = k  # size of reservoir
        self.key = key  # comparison operator
        self.count = 0  # current number of items in reservoir
        self.index = 0  # how many add operations have happened
        self.reservoir_: List[Any] = []  # initially reservoir is empty
        self.sorted_ = False  # initially it is not sorted (used to avoid re-sorting)
        self.gap = 0  # how many adds to skip (using geometric distribution)
        self.W = (
            1.0  # used for computing geometric distribution of number of adds to skip
        )

    def append(self: Self, item: Any) -> None:
        """Potentially randomly add an item to the reservoir."""
        self.sorted_ = False
        self.index += 1
        if self.count < self.k:
            # Reservoir not yet filled: just append item.
            self.reservoir_.append(item)
            self.count += 1
            return
        if self.gap > 0:
            # Still in the gap, just skip
            self.gap -= 1
            return
        # Update the gap and randomly replace an old item in the reservoir with this one.
        self.W = self.W * math.exp(math.log(random.random()) / self.k)
        self.gap = int(math.floor(math.log(random.random()) / math.log(1 - self.W))) + 1
        j = random.randint(0, self.k - 1)
        self.reservoir_[j] = item

    def __len__(self: Self) -> int:
        """Return the number of items currently in the reservoir."""
        return self.count

    def __iadd__(self: Self, other: "sorted_reservoir | List[Any]") -> Self:
        """Merge another reservoir or list into this one via repeated append."""
        items = other.reservoir_ if isinstance(other, sorted_reservoir) else other
        for item in items:
            self.append(item)
        return self

    @property
    def reservoir(self: Self) -> "list[Any]":
        """Returns a sorted reservoir."""
        if not self.sorted_:
            self.reservoir_ = sorted(self.reservoir_, key=self.key)
            self.sorted_ = True
        return self.reservoir_
