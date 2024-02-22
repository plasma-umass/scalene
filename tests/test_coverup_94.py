# file scalene/scalene_statistics.py:352-363
# lines [354, 355, 359, 360, 362, 363]
# branches []

import os
import pathlib
import pytest
from scalene.scalene_statistics import ScaleneStatistics
from unittest.mock import patch, PropertyMock

@pytest.fixture
def scalene_statistics():
    return ScaleneStatistics()

@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path

def test_output_stats(scalene_statistics, temp_dir):
    pid = 1234
    with patch('scalene.scalene_statistics.ScaleneStatistics.payload_contents', new_callable=PropertyMock) as mock_payload:
        mock_payload.return_value = ['cpu_samples_python']
        scalene_statistics.cpu_samples_python = 10
        scalene_statistics.output_stats(pid, temp_dir)
        out_filename = os.path.join(temp_dir, f"scalene{pid}-{str(os.getpid())}")
        assert os.path.isfile(out_filename)
        with open(out_filename, "rb") as out_file:
            import cloudpickle
            payload = cloudpickle.load(out_file)
            assert payload == [10]
    os.remove(out_filename)
