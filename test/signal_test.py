import signal

iterations = 10

def my_handler(sig, frame):
    global iterations
    print(f"seconds remaining: {iterations}")
    if iterations > 0:
        iterations -= 1
        signal.setitimer(signal.ITIMER_REAL, 1.0, 0)
    
signal.signal(signal.SIGALRM, my_handler)
signal.setitimer(signal.ITIMER_REAL, 1.0, 0)

while iterations:
    signal.pause()
