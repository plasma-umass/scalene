import hashlib
from typing import Any, List

class HashableList(list):
    """
    A child class of the built-in list class that is hashable, making it suitable for use as a key in a dictionary.

    This class overrides the various methods that modify the list so that they set the _hash attribute to None after modification,
    and overrides the `__hash__` method to use the SHA-1 hash of the string representation of the list.
    This way, the next time `__hash__` is invoked, it will recalculate the hash only if the list was modified.
    The exception is the `append` and `extend` methods, which incrementally build up the hash instead of recomputing it.

    """
    def __init__(self, *args : List[Any]) -> None:
        super().__init__(*args)
        self._hash = None

    def __hash__(self) -> int:
        if not self._hash:
            self._hash = self._calculate_hash()
        return self._hash

    def _calculate_hash(self) -> int:
        h = hashlib.sha256()
        for item in self:
            h.update(str(item).encode())
        return int(h.hexdigest(), 16)

    def __setitem__(self, key: int, value: Any) -> None:
        super().__setitem__(key, value)
        self._hash = None

    def __delitem__(self, key: int) -> None:
        super().__delitem__(key)
        self._hash = None

    def append(self, item: Any) -> None:
        # Ensure we have a hash value.
        self.__hash__()
        super().append(item)
        self._hash.update(str(hash(item)).encode())

    def extend(self, items: List[Any]) -> None:
        # Ensure we have a hash value.
        self.__hash__()
        super().extend(items)
        for item in items:
            self._hash.update(str(hash(item)).encode())

    def insert(self, index: int, item: Any) -> None:
        self._hash = None
        super().insert(index, item)

    def remove(self, item: Any) -> None:
        self._hash = None
        index = self.index(item)
        super().remove(item)

    def pop(self, index: int = -1) -> Any:
        self._hash = None
        item = super().pop(index)
        return item

    def reverse(self) -> None:
        self._hash = None
        super().reverse()

    def sort(self, key: Any =None, reverse: bool = False) -> None:
        self._hash = None
        super().sort(key, reverse)
       
