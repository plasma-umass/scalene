import argparse

class ScaleneArguments(argparse.Namespace):
    cpu_only = False
    cpu_percent_threshold = 1
    cpu_sampling_rate = 0.01
    html = False
    malloc_threshold = 100
    outfile = None
    pid = 0
    profile_all = True
    profile_interval = float("inf")
    profile_only = ""
    reduced_profile = False
    use_virtual_time = False
    
    
    
