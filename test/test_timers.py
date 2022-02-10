from curses import nonl
import signal
import time


start = -1
loop = True
def callback(*args):
    global loop
    print(time.perf_counter() - start)
    loop = False

signal.signal(signal.SIGALRM, callback)

start = time.perf_counter()
signal.setitimer(signal.ITIMER_REAL, 5)

i = 0
while loop:
    i += 1
    time.sleep(0.1)