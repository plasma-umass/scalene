# file scalene/scalene_profiler.py:318-325
# lines [318, 319, 320, 321, 322, 323, 325]
# branches []

import pytest
from scalene.scalene_profiler import Scalene
from threading import Lock

# Mocking the necessary parts of Scalene to ensure the test can run
Scalene._Scalene__invalidate_mutex = Lock()
Scalene._Scalene__invalidate_queue = []
Scalene.last_profiled_tuple = lambda: ("filename.py", 123)
Scalene.update_line = staticmethod(lambda: None)

def test_update_profiled():
    # Ensure the queue is empty before the test
    Scalene._Scalene__invalidate_queue.clear()

    # Call the method we want to test
    Scalene.update_profiled()

    # Check postconditions
    assert len(Scalene._Scalene__invalidate_queue) == 1
    assert Scalene._Scalene__invalidate_queue[0] == ("filename.py", 123)

    # Clean up after the test
    Scalene._Scalene__invalidate_queue.clear()

# Run the test
def test_scalene_update_profiled():
    test_update_profiled()
