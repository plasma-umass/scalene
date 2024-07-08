# file scalene/scalene_statistics.py:32-187
# lines [34, 37, 40, 43, 47, 49, 53, 55, 58, 60, 63, 65, 68, 70, 73, 75, 78, 81, 84, 86, 89, 91, 94, 96, 99, 101, 104, 106, 109, 111, 114, 115, 116, 117, 121, 123, 126, 128, 131, 133, 136, 138, 141, 143, 145, 148, 151, 154, 157, 160, 163, 164, 165, 167, 170, 172, 176, 178, 182, 184, 185, 186]
# branches []

import pytest
from collections import defaultdict
from scalene.scalene_statistics import ScaleneStatistics

@pytest.fixture
def scalene_stats():
    stats = ScaleneStatistics()
    yield stats
    # No cleanup required as the object will be garbage collected

def test_scalene_statistics(scalene_stats):
    assert scalene_stats.start_time == 0
    assert scalene_stats.elapsed_time == 0
    assert scalene_stats.alloc_samples == 0
    assert isinstance(scalene_stats.stacks, defaultdict)
    assert isinstance(scalene_stats.cpu_samples_python, defaultdict)
    assert isinstance(scalene_stats.cpu_samples_c, defaultdict)
    assert isinstance(scalene_stats.gpu_samples, defaultdict)
    assert isinstance(scalene_stats.gpu_mem_samples, defaultdict)
    assert isinstance(scalene_stats.cpu_utilization, defaultdict)
    assert isinstance(scalene_stats.core_utilization, defaultdict)
    assert isinstance(scalene_stats.cpu_samples, defaultdict)
    assert isinstance(scalene_stats.malloc_samples, defaultdict)
    assert isinstance(scalene_stats.memory_malloc_samples, defaultdict)
    assert isinstance(scalene_stats.memory_malloc_count, defaultdict)
    assert isinstance(scalene_stats.memory_current_footprint, defaultdict)
    assert isinstance(scalene_stats.memory_max_footprint, defaultdict)
    assert isinstance(scalene_stats.memory_current_highwater_mark, defaultdict)
    assert isinstance(scalene_stats.memory_aggregate_footprint, defaultdict)
    assert isinstance(scalene_stats.memory_python_samples, defaultdict)
    assert isinstance(scalene_stats.memory_free_samples, defaultdict)
    assert isinstance(scalene_stats.memory_free_count, defaultdict)
    assert isinstance(scalene_stats.memcpy_samples, defaultdict)
    assert isinstance(scalene_stats.leak_score, defaultdict)
    assert scalene_stats.allocation_velocity == (0.0, 0.0)
    assert scalene_stats.total_cpu_samples == 0.0
    assert scalene_stats.total_gpu_samples == 0.0
    assert scalene_stats.total_memory_malloc_samples == 0.0
    assert scalene_stats.total_memory_free_samples == 0.0
    assert scalene_stats.current_footprint == 0.0
    assert scalene_stats.max_footprint == 0.0
    assert scalene_stats.max_footprint_python_fraction == 0
    assert scalene_stats.max_footprint_loc is None
    assert isinstance(scalene_stats.memory_footprint_samples, list)
    assert isinstance(scalene_stats.per_line_footprint_samples, defaultdict)
    assert isinstance(scalene_stats.bytei_map, defaultdict)
    assert isinstance(scalene_stats.function_map, defaultdict)
    assert isinstance(scalene_stats.firstline_map, defaultdict)
