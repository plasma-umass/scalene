import random

class reservoir():
    """Implements reservoir sampling to achieve the effect of a uniform random sample."""

    sample_array = []
    total_samples = 0
    max_samples = 0
    next_random_choice = 1
    
    def __init__(self, size=0):
        self.max_samples = size
        self.total_samples = 0
        self.sample_array = []

    def add(self, value):
        self.total_samples += 1
        if self.total_samples <= self.max_samples:
            self.sample_array.append(value)
        else:
            if self.max_samples != len(self.sample_array):
                raise AssertionError
            self.next_random_choice -= 1
            #p = random.randint(0, self.total_samples - 1)
            if self.next_random_choice <= 0: # p < self.max_samples:
                # self.sample_array[p] = value
                self.sample_array[random.randint(0, self.max_samples - 1)] = value
                self.next_random_choice = round(random.expovariate(self.max_samples / self.total_samples), 0)

    def get(self):
        return self.sample_array
    
