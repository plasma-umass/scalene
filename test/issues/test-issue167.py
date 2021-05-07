import time
import numpy as np
import pandas as pd

# this assumes you have memory_profiler installed
# if you want to use "@profile" on a function
# if not, we can ignore it with a pass-through decorator
if 'profile' not in dir():
    def profile(fn):
        return fn 

SIZE = 10_000_000


@profile
def get_mean_for_indicator_poor(df, indicator):
    # poor way to use a groupby here, causes big allocation
    gpby = df.groupby('indicator')
    means = gpby.mean() # means by column
    means_for_ind = means.loc[indicator]
    total = means_for_ind.sum()
    return total

@profile
def get_mean_for_indicator_better(df, indicator, rnd_cols):
    # more memory efficient and faster way to solve this challenge
    df_sub = df.query('indicator==@indicator')[rnd_cols]
    means_for_ind = df_sub.mean() # means by column
    total = means_for_ind.sum() # sum of rows
    return total


@profile
def run():
    arr = np.random.random((SIZE, 10))
    print(f"{arr.shape} shape for our array")
    df = pd.DataFrame(arr)
    rnd_cols = [f"c_{n}" for n in df.columns]
    df.columns = rnd_cols

    # make a big dataframe with an indicator column and lots of random data
    df2 = pd.DataFrame({'indicator' : np.random.randint(0, 10, SIZE)})
    # deliberately overwrite the first df
    df = pd.concat((df2, df), axis=1) # PART OF DEMO - unexpected copy=True forces an expensive copy
    print("Head of our df:")
    print(df.head())
    
    print("Print results to check that we get the result")
    indicator = 2
    print(f"Mean for indicator {indicator} on better implementation {get_mean_for_indicator_better(df, indicator, rnd_cols):0.5f}")
    print(f"Mean for indicator {indicator} on poor implementation: {get_mean_for_indicator_poor(df, indicator):0.5f}")


if __name__ == "__main__":
    run()