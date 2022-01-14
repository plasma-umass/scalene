from decimal import *

def exp(x):
    getcontext().prec += 2
    i, lasts, s, fact, num = 0, 0, 1, 1, 1
    while s != lasts:
        lasts = s
        i += 1
        fact *= i
        num *= x
        s += num / fact
    getcontext().prec -= 2
    print(+s)
    return +s

import time

start = time.time()

print("Original:")


d1_orig = exp(Decimal(150))
d2_orig = exp(Decimal(400))
d3_orig = exp(Decimal(3000))

elapsed_original = time.time() - start

print("Elapsed time, original (s):  ", elapsed_original)

def exp_opt(x):
    getcontext().prec += 2
    i, lasts, s, fact, num = 0, 0, 1, 1, 1
    nf = Decimal(1) ### = num / fact
    while s != lasts:
        lasts = s
        i += 1
        # was: fact *= i
        # was: num *= x
        nf *= (x / i) ### update nf to be num / fact
        s += nf ### was: s += num / fact
    getcontext().prec -= 2
    print(+s)
    return +s

start = time.time()

print("Optimized:")

d1_opt = exp_opt(Decimal(150))
d2_opt = exp_opt(Decimal(400))
d3_opt = exp_opt(Decimal(3000))

elapsed_optimized = time.time() - start

print("Elapsed time, optimized (s): ", elapsed_optimized)
print("Improvement: ", elapsed_original / elapsed_optimized)

assert d1_orig == d1_opt
assert d2_orig == d2_opt
assert d3_orig == d3_opt

print("All equivalent? ", d1_orig == d1_opt and d2_orig == d2_opt and d3_orig == d3_opt)

