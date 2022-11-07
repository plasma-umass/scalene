import faulthandler
import multiprocessing
import os
import signal
import threading
from time import sleep


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
