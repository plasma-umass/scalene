import threading
import sys
import numpy as np

class MyThread(threading.Thread):
    @profile
    def run(self):
        z = 0
        z = np.random.uniform(0,100,size=2 * 50000000);
        print("thread1")


class MyThread2(threading.Thread):
    @profile
    def run(self):
        z = 0
        for i in range(50000000 // 2):
            z += 1
        print("thread2")
            

use_threads = True
# use_threads = False

if use_threads:
    t1 = MyThread()
    t2 = MyThread2()
    t1.start()
    t2.start()
    t1.join()
    t2.join()
else:
    t1 = MyThread()
    t1.run()
    t2 = MyThread2()
    t2.run()
        
