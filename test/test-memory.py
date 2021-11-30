import numpy as np
import sys

x = np.ones((1,1))
print(sys.getsizeof(x) / 1048576)

x = np.ones((1000,1000))
print(sys.getsizeof(x) / 1048576)

x = np.ones((1000,2000))
print(sys.getsizeof(x) / 1048576)

x = np.ones((1000,20000))
print(sys.getsizeof(x) / 1048576)

@profile
def allocate():
    for i in range(100):
        x = np.ones((1000,1000))
        x = np.ones((1,1))
        x = np.ones((1,1))
        x = np.ones((1,1))
        x = np.ones((1000,2000))
        x = np.ones((1,1))
        x = np.ones((1,1))
        x = np.ones((1,1))
        x = np.ones((1000,20000))
        x = 1
        x += 1
        x += 1
        x += 1

allocate()

