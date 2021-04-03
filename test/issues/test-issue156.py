import numpy as np

class A:

    def __init__(self, n):
        self.arr = np.random.rand(n)
        self.lst = [1] * n
        print(n)

if __name__ == '__main__':
    a = A(50_000_000)
