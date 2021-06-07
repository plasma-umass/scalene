import queue
import threading


class ScaleneSigQueue:
    def __init__(self, process):
        self.queue = queue.SimpleQueue()
        self.process = process
        self.thread = None
        self.lock = threading.RLock() # held while processing an item

    def put(self, item):
        self.queue.put(item)

    def get(self):
        return self.queue.get()

    def start(self):
        # We use a daemon thread to defensively avoid hanging if we never join with it
        if not self.thread:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        if self.thread:
            self.queue.put(None)
            # We need to join all threads before a fork() to avoid an inconsistent
            # state, locked mutexes, etc.
            self.thread.join()
            self.thread = None

    def run(self):
        while True:
            item = self.queue.get()
            if item == None:  # None == stop request
                break
            with self.lock:
                self.process(*item)
