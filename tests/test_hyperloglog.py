"""Unit tests for the HyperLogLog cardinality estimator.

HLL has a stated standard error of ~1.04 / sqrt(2**p). At p=12 that's
about 1.6%. Tests allow a wider margin so they don't flake on the
worst-case run for a particular set of input hashes.
"""

from scalene.hyperloglog import HyperLogLog


def test_empty_cardinality_is_zero():
    h = HyperLogLog()
    assert h.cardinality() == 0


def test_small_cardinality_is_exact_via_linear_counting():
    h = HyperLogLog()
    # Use integer items: Python hashes ints to themselves, so the estimate is
    # deterministic across runs. ("frame", i) tuples hash via the per-process
    # randomized string hash of "frame" (PYTHONHASHSEED), which made the tight
    # ±2 bound flake on CI (e.g. estimate 47). Integers keep the test exact.
    for i in range(50):
        h.add(i)
    est = h.cardinality()
    # The linear-counting correction is very accurate at low cardinality.
    assert abs(est - 50) <= 2, f"got {est}, expected ~50"


def test_duplicates_do_not_change_estimate():
    h = HyperLogLog()
    for i in range(100):
        h.add(("frame", i))
    baseline = h.cardinality()
    for _ in range(10):
        for i in range(100):
            h.add(("frame", i))
    assert h.cardinality() == baseline


def test_medium_cardinality_within_error_bound():
    h = HyperLogLog()
    n = 5_000
    for i in range(n):
        h.add(("frame", i))
    est = h.cardinality()
    err = abs(est - n) / n
    assert err < 0.05, f"got {est}, expected ~{n}, err={err:.3%}"


def test_large_cardinality_within_error_bound():
    h = HyperLogLog()
    n = 100_000
    for i in range(n):
        h.add(i)
    est = h.cardinality()
    err = abs(est - n) / n
    # p=12 standard error is ~1.6%; allow 5% so we don't flake.
    assert err < 0.05, f"got {est}, expected ~{n}, err={err:.3%}"


def test_merge_unions_two_sketches():
    a = HyperLogLog()
    b = HyperLogLog()
    # Disjoint sets: union cardinality is the sum.
    for i in range(2_000):
        a.add(("a", i))
    for i in range(2_000):
        b.add(("b", i))
    a.merge(b)
    est = a.cardinality()
    err = abs(est - 4_000) / 4_000
    assert err < 0.05, f"merge estimate {est}, expected ~4000, err={err:.3%}"


def test_merge_with_overlap_does_not_double_count():
    a = HyperLogLog()
    b = HyperLogLog()
    # Identical input → union should match either side's cardinality,
    # not double it. This is the key HLL invariant: register-wise max
    # is idempotent for identical hashes.
    for i in range(3_000):
        a.add(i)
        b.add(i)
    base = a.cardinality()
    a.merge(b)
    assert a.cardinality() == base


def test_clear_resets_to_empty():
    h = HyperLogLog()
    for i in range(1_000):
        h.add(i)
    assert h.cardinality() > 500
    h.clear()
    assert h.cardinality() == 0


def test_precision_validation():
    import pytest

    with pytest.raises(ValueError):
        HyperLogLog(p=3)
    with pytest.raises(ValueError):
        HyperLogLog(p=20)


def test_merge_rejects_mismatched_precision():
    import pytest

    a = HyperLogLog(p=10)
    b = HyperLogLog(p=12)
    with pytest.raises(ValueError):
        a.merge(b)
