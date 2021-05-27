import queue
import threading


class ScaleneSigQueue:
    def __init__(self, process):
        self.queue = queue.SimpleQueue()
        self.process = process

    def put(self, item):
        self.queue.put(item)

    def get(self):
        return self.queue.get()

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.queue.put(None)

    def run(self):
        while True:
            item = self.queue.get()
            if not item:
                break
            self.process(*item)
