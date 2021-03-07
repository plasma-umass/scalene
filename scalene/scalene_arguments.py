import argparse

class ScaleneArguments(argparse.Namespace):

    def __init__(self) -> None:
        self.cpu_only = False
        self.cpu_percent_threshold = 1
        self.cpu_sampling_rate = 0.01
        self.html = False
        self.malloc_threshold = 100
        self.outfile = None
        self.pid = 0
        self.profile_all = False
        self.profile_interval = float("inf")
        self.profile_only = ""
        self.reduced_profile = False
        self.use_virtual_time = False
    
    
    
