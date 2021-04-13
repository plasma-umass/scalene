import argparse


class ScaleneArguments(argparse.Namespace):
    def __init__(self) -> None:
        self.cpu_only = False
        self.cpu_percent_threshold = 1
        # mean seconds between interrupts for CPU sampling.
        self.cpu_sampling_rate = 0.01
        self.html = False
        self.malloc_threshold = 100
        self.outfile = None
        self.pid = 0
        # if we profile all code or just target code and code in its child directories
        self.profile_all = False
        # how long between outputting stats during execution
        self.profile_interval = float("inf")
        # what function pathnames must contain to be output during profiling
        self.profile_only = ""
        # The root of the directory that has the files that should be profiled
        self.program_path = ""
        # reduced profile?
        self.reduced_profile = False
        # do we use virtual time or wallclock time (capturing system time and blocking)?
        self.use_virtual_time = False
