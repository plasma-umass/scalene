import os
import sys
from dataclasses import dataclass
from typing import Tuple


@dataclass
class TimeInfo:
    virtual: float = 0.0
    wallclock: float = 0.0
    sys: float = 0.0
    user: float = 0.0

    # a – b  ➜  a.__sub__(b)
    def __sub__(self, other: "TimeInfo") -> "TimeInfo":
        if not isinstance(other, TimeInfo):
            return NotImplemented  # keeps Python’s numeric‑model semantics
        return TimeInfo(
            virtual=self.virtual - other.virtual,
            wallclock=self.wallclock - other.wallclock,
            sys=self.sys - other.sys,
            user=self.user - other.user,
        )

    # a -= b  ➜  a.__isub__(b)
    def __isub__(self, other: "TimeInfo") -> "TimeInfo":
        if not isinstance(other, TimeInfo):
            return NotImplemented
        self.virtual -= other.virtual
        self.wallclock -= other.wallclock
        self.sys -= other.sys
        self.user -= other.user
        return self


def get_times() -> Tuple[float, float]:
    if sys.platform != "win32":
        # On Linux/Mac, use getrusage, which provides higher
        # resolution values than os.times() for some reason.
        import resource

        ru = resource.getrusage(resource.RUSAGE_SELF)
        now_sys = ru.ru_stime
        now_user = ru.ru_utime
    else:
        time_info = os.times()
        now_sys = time_info.system
        now_user = time_info.user
    return now_sys, now_user
