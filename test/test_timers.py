import signal
import time


start = -1
loop = 10
def callback(*args):
    global loop
    global start
    print(time.perf_counter() - start)
    start = time.perf_counter()
    loop -= 1

signal.signal(signal.SIGALRM, callback)

start = time.perf_counter()
signal.setitimer(signal.ITIMER_REAL, 5, 1)

i = 0
while loop > 0:
    i += 1
    time.sleep(0.1)