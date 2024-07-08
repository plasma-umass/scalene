# file scalene/scalene_statistics.py:242-246
# lines [244, 245, 246]
# branches ['244->245', '244->246']

import time
from scalene.scalene_statistics import ScaleneStatistics

def test_stop_clock():
    stats = ScaleneStatistics()
    # Set the start_time to a non-zero value to ensure the if condition is met
    stats.start_time = time.time()
    # Sleep for a short duration to simulate elapsed time
    time.sleep(0.1)
    stats.stop_clock()
    # Check if elapsed_time has been updated
    assert stats.elapsed_time > 0
    # Check if start_time has been reset to 0
    assert stats.start_time == 0
