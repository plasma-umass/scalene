from typing import Tuple


class ScaleneClientTimer:
    """
    A class to wrap the logic of a timer running at
    a different frequency than the Scalene timer. Can handle at most
    one timer.
    """

    seconds: float
    interval: float
    remaining_seconds: float
    remaining_interval: float
    delay_elapsed: bool

    is_set: bool

    def __init__(self) -> None:
        self.seconds = 0.0
        self.interval = 0.0
        self.is_set = False

    def set_itimer(self, seconds: float, interval: float) -> None:
        self.seconds = seconds
        self.interval = interval
        self.remaining_seconds = seconds
        self.remaining_interval = interval
        self.delay_elapsed = False
        self.is_set = True

    def reset(self) -> None:
        """Reset the timer."""
        self.seconds = 0.0
        self.interval = 0.0
        self.is_set = False

    def get_itimer(self) -> Tuple[float, float]:
        """Returns a tuple of (seconds, interval)."""
        return self.seconds, self.interval

    def yield_next_delay(self, elapsed: float) -> Tuple[bool, float]:
        """
        Updates remaining_interval or remaining_seconds, returning whether
        the timer signal should be passed up to the client and
        the next delay. If the second return <= 0, then
        there is no interval and the delay has elapsed.
        """
        if self.delay_elapsed:
            self.remaining_interval -= elapsed

            is_done = self.remaining_interval <= 0
            if is_done:
                self.remaining_interval = self.interval
            return is_done, self.remaining_interval

        self.remaining_seconds -= elapsed
        is_done = self.remaining_seconds <= 0
        if is_done:
            self.delay_elapsed = True
        return (
            is_done,
            self.remaining_interval if is_done else self.remaining_seconds,
        )
