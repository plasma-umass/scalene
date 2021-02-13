import math
import numpy as np
from numpy.random import default_rng
from typing import Any, List, Tuple

rng = default_rng()


def zlog(x: float) -> float:
    """Redefine log so that if x is <= 0, log x is 0."""
    if x <= 0:
        return 0
    else:
        return math.log(x)


def xform(i: float, n: int) -> float:
    assert n > 0
    return i / n * zlog(i / n)


import operator as op
from functools import reduce


def ncr(n: int, r: int) -> int:
    r = min(r, n - r)
    numer = reduce(op.mul, range(n, n - r, -1), 1)
    denom = reduce(op.mul, range(1, r + 1), 1)
    return numer // denom  # or / in Python 2


def choose(n: int, k: int) -> int:
    """
    A fast way to calculate binomial coefficients by Andrew Dalke (contrib).
    """
    if 0 <= k <= n:
        ntok = 1
        ktok = 1
        for t in range(1, min(k, n - k) + 1):
            ntok *= n
            ktok *= t
            n -= 1
        return ntok // ktok
    else:
        return 0


def approx_binomial(total: int, observed: int, success: float) -> float:
    n = total
    p = success
    q = 1 - success
    k = observed
    return (
        1
        / math.sqrt(2 * math.pi * n * p * q)
        * math.exp(-((k - n * p) ** 2) / (2 * n * p * q))
    )


def exact_binomial(total: int, observed: int, success: float) -> float:
    c = choose(total, observed)
    return (
        c
        * (success ** observed)  # pow(success, observed)
        * (1.0 - success)
        ** (total - observed)  # pow(1.0 - success, total - observed)
    )


def binomial(total: int, observed: int, success: float) -> float:
    if total * success > 100 and total * (1.0 - success) > 100:
        return approx_binomial(total, observed, success)
    else:
        return exact_binomial(total, observed, success)


def one_sided_binomial_test_ge(
    total: int, observed: int, success: float
) -> float:
    return sum(binomial(total, o, success) for o in range(observed, total + 1))


def one_sided_binomial_test_lt(
    total: int, observed: int, success: float
) -> float:
    return 1.0 - one_sided_binomial_test_ge(total, observed, success)


def normalized_entropy(v: List[Any]) -> float:
    """Returns a value between 0 (all mass concentrated in one item) and 1 (uniformly spread)."""
    assert len(v) > 0
    if len(v) == 1:
        return 1
    n = int(np.nansum(v))
    assert n > 0
    h = -sum([xform(i, n) for i in v])
    return h / math.log(len(v))


def multinomial_pvalue(vec: List[Any], trials: int = 2000) -> float:
    """Returns the empirical likelihood (via Monte Carlo trials) of randomly finding a vector with as low entropy as this one."""
    n = np.nansum(vec)
    newvec = list(filter(lambda x: not np.isnan(x), vec))
    m = len(newvec)
    ne = normalized_entropy(newvec)
    sampled_vec = rng.multinomial(n, [1 / m for i in range(m)], trials)
    # Return the fraction of times the sampled vector has no more entropy than the original vector
    return sum(normalized_entropy(v) <= ne for v in sampled_vec) / trials


def argmax(vec: List[Any]) -> int:
    """Return the (first) index with the maximum value."""
    m = np.nanmax(vec)
    for (index, value) in enumerate(vec):
        if value == m:
            return index
    return 0  # never reached


def harmonic_number(n: int) -> float:
    """Returns an approximate value of n-th harmonic number.

    http://en.wikipedia.org/wiki/Harmonic_number

    """
    if n < 100:
        return sum(1 / d for d in range(2, n + 1))
    # Euler-Mascheroni constant
    gamma = 0.57721566490153286060651209008240243104215933593992
    return (
        gamma
        + math.log(n)
        + 0.5 / n
        - 1.0 / (12 * n ** 2)
        + 1.0 / (120 * n ** 4)
    )


def outliers(
    vec: List[Any], alpha: float = 0.01, trials: int = 3000
) -> List[Tuple[int, float]]:
    """Returns the indices with values that are significant outliers, with their p-values"""
    m = len(vec)
    if m == 0:
        return []
    removed = 0
    results = []
    # pv = multinomial_pvalue(vec, trials)
    # Hack: for now, set pv to alpha because computing exact multinomial p-values is too expensive
    pv = alpha
    # We use the Benjamin-Yekutieli procedure to control false-discovery rate.
    # See https://en.wikipedia.org/wiki/False_discovery_rate#Benjamini%E2%80%93Yekutieli_procedure
    c_m = harmonic_number(m)
    if pv <= alpha:
        while removed < m:
            # While we remain below the threshold, remove (zero-out by
            # setting to NaN) the max and add its index to the list of
            # results with its p-value.
            max_index = argmax(vec)
            # See how unlikely this bin is to have occurred at random,
            # assuming a uniform distribution into bins.
            this_pvalue = one_sided_binomial_test_ge(
                int(np.nansum(vec)), vec[max_index], 1 / (m - removed)
            )
            # print("max_index = ", max_index, "p-value = ", this_pvalue)
            if this_pvalue <= (alpha * (removed + 1) / (m * c_m)):
                results.append((max_index, this_pvalue))
                vec[max_index] = np.nan
                removed += 1
            else:
                break
    return results


if __name__ == "__main__":
    # Run a simple test.
    print(outliers([1000, 8, 8, 1, 0], alpha=0.01, trials=10000))
    print(outliers([8, 8, 1, 0], alpha=0.01, trials=10000))
    print(outliers([8, 1, 0], alpha=0.01, trials=10000))
    print(outliers([1, 0], alpha=0.01, trials=10000))
