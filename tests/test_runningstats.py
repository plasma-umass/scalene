from scalene import runningstats

import math
import pytest

from typing import List

# hypothesis has no wheel for free-threaded CPython 3.13 and its source
# build fails there (PyO3 doesn't support free-threaded < 3.14), so CI
# installs it best-effort. Skip rather than error out collection.
pytest.importorskip("hypothesis")

import hypothesis.strategies as st  # noqa: E402

from hypothesis import given  # noqa: E402

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
