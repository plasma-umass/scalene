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


# A standalone script, not a pytest test. Its name still matches pytest's
# test_*.py, so keep it from arming a repeating SIGALRM timer at import time:
# that timer outlived collection, firing every second for the rest of the
# test session and, after a --collect-only run, killing pytest at exit.
if __name__ == "__main__":
    signal.signal(signal.SIGALRM, callback)

    start = time.perf_counter()
    signal.setitimer(signal.ITIMER_REAL, 5, 1)

    i = 0
    while loop > 0:
        i += 1
        time.sleep(0.1)
    signal.setitimer(signal.ITIMER_REAL, 0)
