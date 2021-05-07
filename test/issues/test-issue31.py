import numpy as np

def main1():
    # Before optimization
    x = np.array(range(10**7))
    y = np.array(np.random.uniform(0, 100, size=10**8))

def main2():
    # After optimization, spurious `np.array` removed.
    x = np.array(range(10**7))
    y = np.random.uniform(0, 100, size=10**8)

main1()
main2()


