import queue
import threading
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


class ScaleneSigQueue(Generic[T]):
    def __init__(self, process: Any) -> None:
        self.queue: queue.SimpleQueue[Optional[T]] = queue.SimpleQueue()
        self.process = process
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()  # held while processing an item

    def put(self, item: Optional[T]) -> None:
        self.queue.put(item)

    def get(self) -> Optional[T]:
        return self.queue.get()

    def start(self) -> None:
        # We use a daemon thread to defensively avoid hanging if we never join with it
        if not self.thread:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self) -> None:
        if self.thread:
            self.queue.put(None)
            # We need to join all threads before a fork() to avoid an inconsistent
            # state, locked mutexes, etc.
            self.thread.join()
            self.thread = None

    def run(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:  # None => stop request
                break
            with self.lock:
                self.process(*item)
