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
