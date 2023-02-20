import pandas as pd
import numpy as np
import timeit

np.random.seed(1)

column_names_example = [i for i in range(10000)]
index = pd.MultiIndex.from_tuples([("left", c) for c in column_names_example] + [("right", c) for c in column_names_example])
df = pd.DataFrame(np.random.rand(1000, 20000), columns=index)

def keep_column(left_col, right_col):
    return left_col[left_col.first_valid_index()] > right_col[right_col.last_valid_index()]

def do_it():
    v = [c for c in column_names_example if keep_column(df["left"][c], df["right"][c])]
    return v

do_it()
