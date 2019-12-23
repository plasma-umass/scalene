import numpy as np

from numpy import linalg as LA

def doit1(x):
#    x = [i*i for i in range(1,1000)][0]
#    y = np.random.randint(1, 100, size=50000000)[49999999]
    y = 1
    # w, v = LA.eig(np.diag((1, 2, 3, 4, 5, 6, 7, 8, 9, 10)))
    x = [i*i for i in range(0,10000)][9999]
    y1 = [i*i for i in range(0,20000)][19999]
    z1 = [i*i for i in range(0,30000)][29999]
    z = x * y
#    z = np.multiply(x, y)
    return z

def doit2(x):
    z = x * x
    z = z * z
    z = z * z
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
    x = 1.01
    for i in range(1,2):
        for j in range(1,10):
            #print("WO")
            x = doit1(x)
            x = doit2(x)
            x = doit3(x)
            x = 1.01
    return x

stuff()

