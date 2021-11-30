import numpy as np
import sys

x = np.ones((1000,1000))
print(sys.getsizeof(x) / 1048576)

x = np.ones((10000,1000))
print(sys.getsizeof(x) / 1048576)
    
x = np.ones((10000,500))
print(sys.getsizeof(x) / 1048576)
    
for i in range(10):
    x = np.ones((10000,1000))
    x = np.ones((10000,500))
    q = 0
    for z in range(1000):
        q += 1
    x = np.ones((1000,1000))

