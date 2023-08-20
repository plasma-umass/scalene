from . import scalene_json

from hypothesis import given
from hypothesis.strategies import floats, lists


class TestScaleneJSON:
    # Define strategies for the input variables
    size_in_mb = floats(min_value=0.0, allow_nan=False, allow_infinity=False)
    time_in_ms = floats(min_value=0.0, allow_nan=False, allow_infinity=False)
    max_footprint = floats(
        min_value=0.0, allow_nan=False, allow_infinity=False
    )
    samples = lists(
        elements=floats(min_value=0.0, allow_nan=False, allow_infinity=False),
        min_size=0,
    )

    @given(size_in_mb)
    def test_memory_consumed_str(self, size_in_mb):
        formatted = scalene_json.ScaleneJSON().memory_consumed_str(size_in_mb)
        assert isinstance(formatted, str)
        if size_in_mb < 1024:
            assert formatted.endswith("MB")
        elif size_in_mb < 1024 * 1024:
            assert formatted.endswith("GB")
        else:
            assert formatted.endswith("TB")

    @given(time_in_ms)
    def test_time_consumed_str(self, time_in_ms):
        formatted = scalene_json.ScaleneJSON().time_consumed_str(time_in_ms)
        assert isinstance(formatted, str)
        if time_in_ms < 1000:
            assert formatted.endswith("ms")
        elif time_in_ms < 60 * 1000:
            assert formatted.endswith("s")
        elif time_in_ms < 60 * 60 * 1000:
            assert formatted.endswith("s")
        else:
            assert formatted.endswith("s")
            assert not formatted.startswith("0")

    @given(samples, max_footprint)
    def test_compress_samples(self, samples, max_footprint):
        compressed = scalene_json.ScaleneJSON().compress_samples(
            samples, max_footprint
        )
        assert isinstance(compressed, list)
        assert all(isinstance(x, float) for x in compressed)
