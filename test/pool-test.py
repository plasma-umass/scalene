
import multiprocessing
# import logging
# log = multiprocessing.get_logger()
# log.setLevel(logging.DEBUG)
# log.addHandler(logging.StreamHandler())
from multiprocessing import Pool

def f(x):
    print("Start")
    return [i for i in range(1000000)]

if __name__ == '__main__':
    with Pool(5) as p:
        q = p.map(f, [1, 2, 3])
        print(len(q))
