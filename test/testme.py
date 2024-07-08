#!/usr/bin/env python3
import numpy as np
#import math

# from numpy import linalg as LA

arr = [i for i in range(1,1000)]

def doit1(x):
    y = 1
    x = [i*i for i in range(0,100000)][99999]
    y1 = [i*i for i in range(0,200000)][199999]
    z1 = [i for i in range(0,300000)][299999]
    z = x * y * y1 * z1
    return z

def doit2(x):
    i = 0
    z = 0.1
    while i < 100000:
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
    return z

def stuff():
#    y = np.random.randint(1, 100, size=50000000)[49999999]
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

