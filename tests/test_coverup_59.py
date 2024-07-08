# file scalene/adaptive.py:4-43
# lines [4, 5, 7, 9, 10, 11, 13, 14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 26, 27, 29, 30, 31, 32, 33, 34, 35, 36, 37, 39, 40, 42, 43]
# branches ['15->16', '15->17', '21->22', '21->23', '27->29', '27->36', '30->31', '30->34']

import pytest
from scalene.adaptive import Adaptive

def test_adaptive_add():
    size = 8
    adaptive1 = Adaptive(size)
    adaptive2 = Adaptive(size)

    # Fill adaptive1 and adaptive2 with values to trigger decimation
    for i in range(size):
        adaptive1.add(i)
        adaptive2.add(size - i)

    # Perform addition
    adaptive_sum = adaptive1 + adaptive2

    # Check postconditions
    assert adaptive_sum.len() == size
    for i in range(size):
        assert adaptive_sum.get()[i] == adaptive1.get()[i] + adaptive2.get()[i]

    # Check if decimation occurred
    adaptive1.add(100)
    assert adaptive1.len() == size // 3 + 1

    # Check if the median was correctly calculated
    for i in range(size // 3):
        arr = [i * 3, i * 3 + 1, i * 3 + 2]
        arr.sort()
        assert adaptive1.get()[i] == arr[1]  # Median

def test_adaptive_iadd():
    size = 8
    adaptive1 = Adaptive(size)
    adaptive2 = Adaptive(size)

    # Fill adaptive1 and adaptive2 with values to trigger decimation
    for i in range(size):
        adaptive1.add(i)
        adaptive2.add(size - i)

    # Perform in-place addition
    adaptive1 += adaptive2

    # Check postconditions
    assert adaptive1.len() == size
    for i in range(size):
        assert adaptive1.get()[i] == i + (size - i)

    # Check if decimation occurred
    adaptive1.add(100)
    assert adaptive1.len() == size // 3 + 1

    # Check if the median was correctly calculated
    for i in range(size // 3):
        # Since we are adding the arrays before decimation, we need to calculate the median of the sums
        arr = [i * 3 + (size - i * 3), i * 3 + 1 + (size - i * 3 - 1), i * 3 + 2 + (size - i * 3 - 2)]
        arr.sort()
        assert adaptive1.get()[i] == arr[1]  # Median of the sums
