from scalene import runningstats

import hypothesis.strategies as st
import math
import statistics

from hypothesis import given
from typing import List

TOLERANCE = 0.5

@given(
    st.lists(
        st.floats(
            allow_infinity=False, allow_nan=False, min_value=0.5, max_value=1e9
        ),
        min_size=2,
    )
)
def test_running_stats(values: List[float]) -> None:
    rstats = runningstats.RunningStats()
    for value in values:
        rstats.push(value)

    assert len(values) == rstats.size()
    assert max(values) == rstats.peak()
    assert math.isclose(sum(values) / len(values), rstats.mean(), rel_tol=TOLERANCE)
    assert math.isclose(
        statistics.variance(values, xbar=rstats.mean()),
        rstats.var(),
        rel_tol=TOLERANCE,
    )
    assert math.isclose(
        statistics.stdev(values, xbar=rstats.mean()),
        rstats.std(),
        rel_tol=TOLERANCE,
    )
    assert math.isclose(
        statistics.stdev(values, xbar=rstats.mean())
        / math.sqrt(rstats.size()),
        rstats.sem(),
        rel_tol=TOLERANCE,
    )
