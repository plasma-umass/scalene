import multiprocessing
import faulthandler
import os
import signal
from time import sleep
import threading

def do_very_little():
    sleep(1)
    print("In subprocess")
    print(threading.enumerate())

if __name__ == "__main__":
    print("Starting")
    p = multiprocessing.Process(target=do_very_little)
    p.start()
    print("Joining")
    p.join()
    print("Joined", p)

    print("exiting")