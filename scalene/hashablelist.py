import hashlib

class HashableList(list):
    """
    A child class of the built-in list class that is hashable, making it suitable for use as a key in a dictionary.

    This class overrides the various methods that modify the list so that they set the _hash attribute to None after modification,
    and overrides the `__hash__` method to use the SHA-1 hash of the string representation of the list.
    This way, the next time `__hash__` is invoked, it will recalculate the hash only if the list was modified.

    """
    def __init__(self, *args):
        super().__init__(*args)
        self._hash = None

    def __hash__(self):
        if self._hash is None:
            self._hash = int(hashlib.sha1(str(self).encode()).hexdigest(), 16)
        return self._hash

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        self._hash = None

    def __delitem__(self, index):
        super().__delitem__(index)
        self._hash = None

    def append(self, value):
        super().append(value)
        self._hash = None

    def extend(self, iterable):
        super().extend(iterable)
        self._hash = None

    def insert(self, index, value):
        super().insert(index, value)
        self._hash = None

    def pop(self, index=-1):
        super().pop(index)
        self._hash = None

    def remove(self, value):
        super().remove(value)
        self._hash = None

    def reverse(self):
        super().reverse()
        self._hash = None

    def sort(self, key=None, reverse=False):
        super().sort(key, reverse)
        self._hash = None
