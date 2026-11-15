"""Test that Scalene correctly handles user code with setitimer/SIGALRM.

This is a regression test for signals not being restarted properly.
It checks whether the program halts or runs forever, not for correctness of timing.

The test uses short intervals (0.1s) to:
1. Complete quickly (~1 second total)
2. Reduce timing sensitivity on busy CI machines
3. Still effectively test the signal restart mechanism

It sleeps in short steps rather than calling signal.pause(): an alarm
arriving just before pause() blocks has its Python handler run only after
pause() returns, so the next alarm is never armed and pause() waits forever
(a race in the test itself, seen once on CI). If Scalene broke the user's
timer, the iterations would stop and this loop would still run forever.
"""

import signal
import time

iterations = 10
interval = 0.1  # Use short intervals for robustness


def my_handler(sig, frame):
    global iterations
    print(f"iterations remaining: {iterations}")
    if iterations > 0:
        iterations -= 1
        signal.setitimer(signal.ITIMER_REAL, interval, 0)


signal.signal(signal.SIGALRM, my_handler)
signal.setitimer(signal.ITIMER_REAL, interval, 0)

while iterations:
    time.sleep(0.01)

print("Signal test completed successfully")
