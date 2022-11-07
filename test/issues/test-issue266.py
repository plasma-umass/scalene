import gc

import numpy as np
import pandas as pd


def f():
    print('called f')
    #Uses around 4GB of memory when looped once
    df = np.ones(500000000)

#Uses around 20GB of memory when looped 5 times
for i in range(0,5):
    f()
