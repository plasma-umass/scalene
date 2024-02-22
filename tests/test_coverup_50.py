# file scalene/replacement_sem_lock.py:9-33
# lines [9, 10, 12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 29, 30, 32, 33]
# branches ['12->13', '12->14', '19->20', '24->25', '24->27']

import multiprocessing
import pytest
import random
import sys
import threading
from scalene.replacement_sem_lock import ReplacementSemLock
from scalene.scalene_profiler import Scalene

# Mock Scalene methods used in ReplacementSemLock
Scalene.set_thread_sleeping = lambda x: None
Scalene.reset_thread_sleeping = lambda x: None

@pytest.fixture
def replacement_sem_lock():
    lock = ReplacementSemLock()
    yield lock
    if lock._semlock._is_zero():
        lock.release()

def test_replacement_sem_lock_enter_exit(replacement_sem_lock):
    # Test the __enter__ method with a forced timeout
    original_random = random.random
    original_interval = sys.getswitchinterval()
    sys.setswitchinterval(0.000001)  # Set a very small interval to force a timeout
    random.random = lambda: 1  # Force the maximum timeout

    try:
        with replacement_sem_lock:
            pass  # This block should be executed
    finally:
        # Restore the original functions
        random.random = original_random
        sys.setswitchinterval(original_interval)

    # Test the __exit__ method
    assert not replacement_sem_lock._semlock._is_zero(), "Lock should not be acquired yet"
    with replacement_sem_lock:
        assert replacement_sem_lock._semlock._is_zero(), "Lock should be acquired"
    assert not replacement_sem_lock._semlock._is_zero(), "Lock should be released after the block"

def test_replacement_sem_lock_reduce(replacement_sem_lock):
    # Test the __reduce__ method
    reduced = replacement_sem_lock.__reduce__()
    assert callable(reduced[0]), "__reduce__ should return a callable as the first element"
    assert reduced[1] == (), "__reduce__ should return an empty tuple as the second element"
