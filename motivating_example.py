from itertools import count, compress, islice
from math import isqrt

def sieve(n):
   'Primes less than n'
   data = bytearray([1]) * n
   data[:2] = 0, 0
   limit = isqrt(n) + 1
   for c in compress(count(), islice(data, limit)):
      data[c+c::c] = bytearray(len(range(c+c, n, c)))
   return list(compress(count(), data))

l = sieve(10**9)
