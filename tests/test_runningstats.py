from scalene import runningstats

import hypothesis.strategies as st
import math

from hypothesis import given
from typing import List

TOLERANCE = 0.5


@given(
    st.lists(
        st.floats(allow_infinity=False, allow_nan=False, min_value=0.5, max_value=1e9),
        min_size=2,
    )
)
def test_running_stats(values: List[float]) -> None:
    """Test RunningStats computes mean and peak correctly."""
    rstats = runningstats.RunningStats()
    for value in values:
        rstats.push(value)

    assert len(values) == rstats.size()
    assert max(values) == rstats.peak()
    assert math.isclose(sum(values) / len(values), rstats.mean(), rel_tol=TOLERANCE)
