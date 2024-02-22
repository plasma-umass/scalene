# file scalene/scalene_output.py:84-300
# lines [84, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 101, 102, 103, 104, 105, 106, 107, 108, 110, 111, 112, 114, 117, 118, 119, 120, 123, 124, 127, 128, 129, 130, 132, 133, 134, 135, 136, 137, 140, 141, 142, 143, 147, 148, 150, 151, 153, 154, 155, 156, 158, 159, 161, 163, 164, 165, 166, 170, 171, 172, 173, 176, 177, 178, 182, 183, 184, 185, 187, 188, 189, 190, 193, 194, 195, 196, 197, 199, 201, 202, 204, 205, 207, 208, 210, 211, 214, 215, 216, 217, 219, 220, 222, 223, 224, 225, 227, 228, 229, 230, 233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 247, 248, 249, 250, 251, 252, 253, 254, 255, 256, 261, 262, 263, 264, 265, 266, 267, 269, 270, 272, 273, 276, 277, 278, 280, 281, 282, 283, 284, 285, 286, 287, 288, 289, 292, 293, 294, 295, 296, 297, 300]
# branches ['110->111', '110->112', '112->114', '112->117', '133->134', '133->140', '150->151', '150->153', '158->159', '158->261', '163->164', '163->170', '176->177', '176->182', '192->201', '192->214', '219->220', '219->222', '233->234', '233->247', '261->266', '261->276', '280->281', '280->282', '282->283', '282->292']

import pytest
from scalene.scalene_output import ScaleneOutput
from scalene.scalene_json import ScaleneJSON
from scalene.scalene_statistics import ScaleneStatistics
from rich.console import Console
from rich.table import Table
from typing import Callable
from collections import defaultdict
import random

@pytest.fixture
def scalene_output():
    return ScaleneOutput()

@pytest.fixture
def scalene_json():
    return ScaleneJSON()

@pytest.fixture
def scalene_stats():
    stats = ScaleneStatistics()
    stats.cpu_samples = defaultdict(lambda: defaultdict(float))
    stats.memory_free_samples = defaultdict(lambda: defaultdict(list))
    stats.memory_malloc_samples = defaultdict(lambda: defaultdict(list))
    return stats

@pytest.fixture
def console():
    return Console()

@pytest.fixture
def table():
    return Table()

def test_output_profile_line(scalene_output, scalene_json, scalene_stats, console, table):
    fname = "test.py"
    line_no = 1
    line = "print('Hello, world!')"
    profile_this_code: Callable[[str, int], bool] = lambda fname, line_no: True

    # Set up statistics to trigger different branches
    scalene_stats.total_cpu_samples = 100
    scalene_stats.cpu_samples[fname][line_no] = 2
    scalene_stats.cpu_samples["<other>"][1] = 98
    scalene_stats.memory_free_samples[fname][line_no] = [(0, 0.5)]
    scalene_stats.memory_malloc_samples[fname][line_no] = [(0, 0.5)]
    scalene_stats.max_footprint = 1024

    # Set up JSON output to trigger different branches
    json_output = {
        "n_peak_mb": 0.5,
        "n_cpu_percent_c": 0.5,
        "n_gpu_percent": 0.5,
        "n_cpu_percent_python": 0.5,
        "n_usage_fraction": 0.5,
        "n_sys_percent": 0.5,
        "n_python_fraction": 0.5,
        "n_copy_mb_s": 0.5,
        "memory_samples": [(0, 0.5)],
    }
    scalene_json.output_profile_line = lambda **kwargs: json_output

    # Set up output to trigger different branches
    scalene_output.highlight_percentage = 0.1
    scalene_output.highlight_color = "red"
    scalene_output.gpu = True
    scalene_output.max_sparkline_len_line = 1

    # Mock random.sample to return a predictable result
    random.sample = lambda a, _: a

    # Call the method under test
    result = scalene_output.output_profile_line(
        json=scalene_json,
        fname=fname,
        line_no=line_no,
        line=line,
        console=console,
        tbl=table,
        stats=scalene_stats,
        profile_this_code=profile_this_code,
        force_print=False,
        suppress_lineno_print=False,
        is_function_summary=False,
        profile_memory=True,
        reduced_profile=False,
    )

    # Check postconditions
    assert result == True
    assert len(table.rows) == 1
    # Clean up
    del scalene_output
    del scalene_json
    del scalene_stats
    del console
    del table
    random.sample = random.Random().sample  # Restore the original random.sample
