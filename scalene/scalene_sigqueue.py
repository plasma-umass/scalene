import queue
import threading


class ScaleneSigQueue:
    def __init__(self, process):
        self.queue = queue.SimpleQueue()
        self.process = process
        self.thread = None

    def put(self, item):
        self.queue.put(item)

    def get(self):
        return self.queue.get()

    def start(self):
        assert not self.thread
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        if self.thread:
            self.queue.put(None)
            self.thread.join()
            self.thread = None

    def run(self):
        while True:
            item = self.queue.get()
            if item == None:  # None == stop request
                break
            self.process(*item)
