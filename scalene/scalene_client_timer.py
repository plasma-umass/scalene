from typing import Tuple


class ScaleneClientTimer:
    seconds: float
    interval: float
    remaining_seconds: float
    remaining_interval: float
    delay_elapsed: bool

    is_set: bool

    def __init__(self):
        self.seconds = 0.0
        self.interval = 0.0
        self.is_set = False

    def set_itimer(self, seconds: float, interval: float):
        self.seconds = seconds
        self.interval = interval
        self.remaining_seconds = seconds
        self.remaining_interval = interval
        self.delay_elapsed = False
        self.is_set = True

    def reset(self):
        self.seconds = 0.0
        self.interval = 0.0
        self.is_set = False
    def get_itimer(self) -> Tuple[float, float]:
        return self.seconds, self.interval

    def yield_next_delay(self, elapsed) -> Tuple[bool, float]:
        if self.delay_elapsed:
            self.remaining_interval -= elapsed

            is_done = self.remaining_interval <= 0
            if is_done:
                self.remaining_interval = self.interval
            return is_done, self.remaining_interval
        else:
            self.remaining_seconds -= elapsed
            is_done = self.remaining_seconds <= 0
            if is_done:
                self.delay_elapsed = True
            return is_done, self.remaining_interval if is_done else self.remaining_seconds