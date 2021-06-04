import logging
import multiprocessing
from time import sleep, perf_counter
# import faulthandler
# faulthandler.enable()
# import signal
# import os
# multiprocessing.log_to_stderr(logging.DEBUG)
# from multiprocessing.spawn import spawn_main
# import scalene.replacement_pjoin
# Stolen from https://stackoverflow.com/questions/15347174/python-finding-prime-factors

class Integer(object):
    def __init__(self, x):
        self.x = x

def largest_prime_factor(n):
    for i in range(10):
        x = [Integer(i * i) for i in range(80000)]
        # sleep(1)
        a = x[50]
        print("\033[91mprogress ", n, i, a.x, '\033[0m')
    print("Done")

# range_obj = range (65535588555555555, 65535588555555557)
range_obj = range(4)
if __name__ == "__main__":
    # import __main__
    # x = [largest_prime_factor(i) for i in range_obj]
    t0 = perf_counter()
    handles = [multiprocessing.Process(target=largest_prime_factor, args=(i,)) for i in range_obj]
    # handles = [multiprocessing.Process(target=largest_prime_factor, args=(1000000181,))]
    
    for handle in handles:
        print("Starting", handle)
        handle.start()
    # multiprocessing.popen_fork.Popen
    
    # try:
    for handle in handles:
        print("Joining", handle)
        handle.join()
    # except KeyboardInterrupt:
    #     for handle in handles:
    #         try:
    #             os.kill(handle.pid, signal.SIGSEGV)
    #         except:
    #             pass
    #     exit(1)
    dt = perf_counter() - t0
    print(f"Total time: {dt}")
