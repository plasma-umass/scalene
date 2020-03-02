import math
import random

class reservoir():
    """Implements reservoir sampling to achieve the effect of a uniform random sample."""

    sample_array = []
    total_samples = 0
    max_samples = 0
    
    def __init__(self, size=0):
        self.max_samples = size
        self.total_samples = 0
        self.sample_array = []

    def add(self, value):
        self.total_samples += 1
        if self.total_samples <= self.max_samples:
            self.sample_array.append(value)
        else:
            assert self.max_samples == len(self.sample_array)
            p = random.randint(0, self.total_samples - 1)
            if p < self.max_samples:
                self.sample_array[p] = value

    def get(self):
        return self.sample_array
    
