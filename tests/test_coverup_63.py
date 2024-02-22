# file scalene/scalene_statistics.py:189-225
# lines [191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 223, 224, 225]
# branches []

import pytest
from scalene.scalene_statistics import ScaleneStatistics

@pytest.fixture
def scalene_statistics():
    stats = ScaleneStatistics()
    # Pre-populate some data to ensure clear() has an effect.
    stats.start_time = 123
    stats.elapsed_time = 456
    stats.alloc_samples = 789
    stats.stacks["test"] = None
    stats.cpu_samples_python["test"] = None
    stats.cpu_samples_c["test"] = None
    stats.cpu_utilization["test"] = None
    stats.core_utilization["test"] = None
    stats.cpu_samples["test"] = None
    stats.gpu_samples["test"] = None
    stats.malloc_samples["test"] = None
    stats.memory_malloc_samples["test"] = None
    stats.memory_malloc_count["test"] = None
    stats.memory_current_footprint["test"] = None
    stats.memory_max_footprint["test"] = None
    stats.memory_current_highwater_mark["test"] = None
    stats.memory_aggregate_footprint["test"] = None
    stats.memory_python_samples["test"] = None
    stats.memory_free_samples["test"] = None
    stats.memory_free_count["test"] = None
    stats.memcpy_samples["test"] = None
    stats.total_cpu_samples = 1.0
    stats.total_gpu_samples = 1.0
    stats.total_memory_malloc_samples = 1.0
    stats.total_memory_free_samples = 1.0
    stats.current_footprint = 1.0
    stats.leak_score["test"] = None
    stats.last_malloc_triggered = (
        "test",
        1,
        "0x1",
    )
    stats.allocation_velocity = (1.0, 1.0)
    stats.per_line_footprint_samples["test"] = None
    stats.bytei_map["test"] = None
    return stats

def test_clear_scalene_statistics(scalene_statistics):
    scalene_statistics.clear()
    assert scalene_statistics.start_time == 0
    assert scalene_statistics.elapsed_time == 0
    assert scalene_statistics.alloc_samples == 0
    assert scalene_statistics.stacks == {}
    assert scalene_statistics.cpu_samples_python == {}
    assert scalene_statistics.cpu_samples_c == {}
    assert scalene_statistics.cpu_utilization == {}
    assert scalene_statistics.core_utilization == {}
    assert scalene_statistics.cpu_samples == {}
    assert scalene_statistics.gpu_samples == {}
    assert scalene_statistics.malloc_samples == {}
    assert scalene_statistics.memory_malloc_samples == {}
    assert scalene_statistics.memory_malloc_count == {}
    assert scalene_statistics.memory_current_footprint == {}
    assert scalene_statistics.memory_max_footprint == {}
    assert scalene_statistics.memory_current_highwater_mark == {}
    assert scalene_statistics.memory_aggregate_footprint == {}
    assert scalene_statistics.memory_python_samples == {}
    assert scalene_statistics.memory_free_samples == {}
    assert scalene_statistics.memory_free_count == {}
    assert scalene_statistics.memcpy_samples == {}
    assert scalene_statistics.total_cpu_samples == 0.0
    assert scalene_statistics.total_gpu_samples == 0.0
    assert scalene_statistics.total_memory_malloc_samples == 0.0
    assert scalene_statistics.total_memory_free_samples == 0.0
    assert scalene_statistics.current_footprint == 0.0
    assert scalene_statistics.leak_score == {}
    assert scalene_statistics.last_malloc_triggered == (
        "",
        0,
        "0x0",
    )
    assert scalene_statistics.allocation_velocity == (0.0, 0.0)
    assert scalene_statistics.per_line_footprint_samples == {}
    assert scalene_statistics.bytei_map == {}
