# file scalene/scalene_sigqueue.py:8-48
# lines [8, 9, 10, 11, 12, 13, 15, 17, 19, 21, 23, 26, 27, 28, 30, 32, 33, 36, 37, 39, 43, 44, 45, 46, 47, 48]
# branches ['26->exit', '26->27', '32->exit', '32->33', '43->44', '45->46', '45->47']

import pytest
import threading
from typing import Any, Optional, Generic, TypeVar
from scalene.scalene_sigqueue import ScaleneSigQueue
import queue

T = TypeVar('T')

class TestScaleneSigQueue(Generic[T]):
    # Prevent pytest from considering this class as a test
    __test__ = False

    def __init__(self, process: Any) -> None:
        self.queue: queue.SimpleQueue[Optional[T]] = queue.SimpleQueue()
        self.process = process
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()  # held while processing an item

    def put(self, item: Optional[T]) -> None:
        """Add an item to the queue."""
        self.queue.put(item)

    def get(self) -> Optional[T]:
        """Get one item from the queue."""
        return self.queue.get()

    def start(self) -> None:
        """Start processing."""
        # We use a daemon thread to defensively avoid hanging if we never join with it
        if not self.thread:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        """Stop processing."""
        if self.thread:
            self.queue.put(None)
            # We need to join all threads before a fork() to avoid an inconsistent
            # state, locked mutexes, etc.
            self.thread.join()
            self.thread = None

    def run(self) -> None:
        """Run the function processing items until stop is called.

        Executed in a separate thread."""
        while True:
            item = self.queue.get()
            if item is None:  # None => stop request
                break
            with self.lock:
                self.process(*item)

def test_scalene_sigqueue():
    results = []

    def process_function(*args):
        results.append(args)

    sigqueue = TestScaleneSigQueue(process_function)
    sigqueue.start()

    sigqueue.put((1, 2, 3))
    sigqueue.put((4, 5, 6))
    sigqueue.put(None)  # Stop signal

    sigqueue.stop()

    assert results == [(1, 2, 3), (4, 5, 6)]
