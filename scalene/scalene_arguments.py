import argparse
import platform
import sys


class ScaleneArguments(argparse.Namespace):
    """Encapsulates all arguments and default values for Scalene."""

    def __init__(self) -> None:
        super().__init__()
        self.cpu = True
        self.gpu = platform.system() != "Darwin"
        self.memory = sys.platform != "win32"
        self.stacks = False  # default - don't collect stack traces
        self.cpu_percent_threshold = 1
        # mean seconds between interrupts for CPU sampling.
        self.cpu_sampling_rate = 0.01
        # Size of allocation window (sample when footprint increases or decreases by this amount)
        self.allocation_sampling_window = (
            10485767  # sync with src/source/libscalene.cpp
            # was 1549351
        )
        self.html = False
        self.json = False
        self.column_width = (
            132  # Note that Scalene works best with at least 132 columns.
        )
        self.malloc_threshold = 100
        self.outfile = None
        self.pid = 0
        # if we profile all code or just target code and code in its child directories
        self.profile_all = False
        # how long between outputting stats during execution
        self.profile_interval = float("inf")
        # what function pathnames must contain to be output during profiling
        self.profile_only = ""
        # what function pathnames should never be output during profiling
        self.profile_exclude = ""
        # The root of the directory that has the files that should be profiled
        self.program_path = ""
        # reduced profile?
        self.reduced_profile = False
        # do we use virtual time or wallclock time (capturing system time and blocking)?
        self.use_virtual_time = False
        self.memory_leak_detector = True  # experimental
        self.web = True
        self.no_browser = False
        self.port = 8088
        self.cli = False
