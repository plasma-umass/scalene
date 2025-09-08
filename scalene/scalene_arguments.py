import argparse
import platform
import sys
from typing import Any, Optional, TypedDict

from typing_extensions import Unpack


class ScaleneArgumentsDict(TypedDict, total=False):
    cpu: bool
    gpu: bool
    memory: bool
    # collect stack traces?
    stacks: bool
    # mean seconds between interrupts for CPU sampling.
    cpu_percent_threshold: int
    cpu_sampling_rate: float
    # Size of allocation window (sample when footprint increases or decreases by this amount)
    # sync with src/source/libscalene.cpp
    allocation_sampling_window: int
    html: bool
    json: bool
    # Note that Scalene works best with at least 132 columns.
    column_width: int
    malloc_threshold: int
    outfile: Optional[str]
    pid: int
    # if we profile all code or just target code and code in its child directories
    profile_all: bool
    # how long between outputting stats during execution
    profile_interval: float
    # what function pathnames must contain to be output during profiling
    profile_only: str
    profile_exclude: str
    # The root of the directory that has the files that should be profiled
    program_path: str
    # Reduced profile? (Limited to lines with above a threshold amount of activity)
    reduced_profile: bool
    # do we use virtual time or wallclock time (capturing system time and blocking)?
    use_virtual_time: bool
    memory_leak_detector: bool
    web: bool
    no_browser: bool
    port: int
    cli: bool


def _set_defaults() -> ScaleneArgumentsDict:
    return {
        "cpu": True,
        "gpu": True,
        "memory": sys.platform != "win32",
        "stacks": False,
        "cpu_percent_threshold": 1,
        "cpu_sampling_rate": 0.01,
        "allocation_sampling_window": 10485767,
        "html": False,
        "json": False,
        "column_width": 132,
        "malloc_threshold": 100,
        "outfile": None,
        "pid": 0,
        "profile_all": False,
        "profile_interval": float("inf"),
        "profile_only": "",
        "profile_exclude": "",
        "program_path": "",
        "reduced_profile": False,
        "use_virtual_time": False,
        "memory_leak_detector": True,
        "web": True,
        "no_browser": False,
        "port": 8088,
        "cli": False,
    }


class ScaleneArguments(argparse.Namespace):
    """Encapsulates all arguments and default values for Scalene."""

    def __init__(self, **kwargs: Unpack[ScaleneArgumentsDict]) -> None:
        super().__init__(**kwargs)
        arg_dict = _set_defaults()
        for key, value in arg_dict.items():
            setattr(self, key, value)
        for key, value in kwargs.items():
            setattr(self, key, value)
        if self.cli or self.json:
            self.web = False
            self.no_browser = True
