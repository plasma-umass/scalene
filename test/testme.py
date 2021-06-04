import numpy as np
#import math

from numpy import linalg as LA

arr = [i for i in range(1,1000)]

def doit1(x):
#    x = [i*i for i in range(1,1000)][0]
    y = 1
#    w, v = LA.eig(np.diag(arr)) # (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)))
    x = [i*i for i in range(0,100000)][99999]
    y1 = [i*i for i in range(0,200000)][199999]
    z1 = [i for i in range(0,300000)][299999]
    z = x * y
#    z = np.multiply(x, y)
    return z

def doit2(x):
    i = 0
#    zarr = [math.cos(13) for i in range(1,100000)]
#    z = zarr[0]
    z = 0.1
    while i < 100000:
#        z = math.cos(13)
#        z = np.multiply(x,x)
#        z = np.multiply(z,z)
#        z = np.multiply(z,z)
        z = z * z
        z = x * x
        z = z * z
        z = z * z
        i += 1
    return z

def doit3(x):
    z = x + 1
    z = x + 1
    z = x + 1
    z = x + z
    z = x + z
#    z = np.cos(x)
    return z

def stuff():
    y = np.random.randint(1, 100, size=5000000)[4999999]
    x = 1.01
    for i in range(1,10):
        print(i)
        for j in range(1,10):
            x = doit1(x)
            x = doit2(x)
            x = doit3(x)
            x = 1.01
    return x

import sys
print("TESTME")
print(sys.argv)
stuff()

