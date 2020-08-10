# Translated from C++ by Emery Berger from https://www.johndcook.com/blog/skewness_kurtosis/

import math

class RunningStats:
    """Incrementally compute statistics"""
    
    def __init__(self):
        self.clear()

    def clear(self):
        """Reset for new samples"""
        self.n = 0
        self.m1 = self.m2 = self.m3 = self.m4 = 0.0

    def push(self, x):
        """Add a sample"""
        n1 = self.n
        self.n += 1
        delta = x - self.m1
        delta_n = delta / self.n
        delta_n2 = delta_n * delta_n
        term1 = delta * delta_n * n1
        self.m1 += delta_n
        self.m4 += term1 * delta_n2 * (self.n*self.n - 3*self.n + 3) + 6 * delta_n2 * self.m2 - 4 * delta_n * self.m3
        self.m3 += term1 * delta_n * (self.n - 2) - 3 * delta_n * self.m2
        self.m2 += term1

    def size(self):
        """The number of samples"""
        return self.n

    def mean(self):
        """Arithmetic mean, a.k.a. average"""
        return self.m1

    def var(self):
        """Variance"""
        return self.m2 / (self.n - 1.0)

    def std(self):
        """Standard deviation"""
        return math.sqrt(self.var())

    def sem(self):
        """Standard error of the mean"""
        return self.std() / math.sqrt(self.n)
    
