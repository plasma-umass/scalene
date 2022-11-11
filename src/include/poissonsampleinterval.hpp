#pragma once
#include <_types/_uint64_t.h>
#include <random>
#include <unordered_map>

/**
 * @brief "triggers" samples using a geometric distribution
 *
 * Sampled recording allocated objects with a rate of every
 * SAMPLE_INTERVAL bytes (on average).
 *
 */

class PoissonSampleInterval {
 public:
  /**
   * @brief Construct a new SampleInterval object
   *
   */
  PoissonSampleInterval(uint64_t SAMPLE_INTERVAL) : gen(rd()), d(1.0 / SAMPLE_INTERVAL) {
    resetAlloc();
  }

  /**
   * @brief Deallocate an object; if sampled, return the size of the recorded sampling interval, else 0.
   *
   * @param sample 
   * @return uint64_t the previous sample interval if we crossed it; 0 otherwise
   */
  inline uint64_t decrement(uint64_t, void * ptr = nullptr) {
    auto found = _allocSize.find(ptr) != _allocSize.end();
    if (!found) {
      // Not found
      return 0;
    } else {
      // It was sampled. Return the recorded size, removing the object first.
      auto sz = _allocSize[ptr];
      _allocSize.erase(ptr);
      return sz;
    }
  }

  /**
   * @brief increment by the sample amount, triggering an interval reset when we
   * cross the threshold
   *
   * @param sample the amount to decrement the sample interval by
   * @return uint64_t the previous sample interval if we crossed it; 0 otherwise
   */
  inline uint64_t increment(uint64_t sample, void * ptr = nullptr) {
    if (unlikely(sample > _tillNextAlloc)) {
      auto prev = _countdownAlloc;
      auto diff = sample - _tillNextAlloc;
      resetAlloc();
      const auto incrementAmount = prev + diff;
      _allocSize[ptr] = incrementAmount;
      return incrementAmount;
    }
    _tillNextAlloc -= sample;
    return 0;
  }

 private:

  std::random_device rd;
  std::mt19937 gen;
  std::geometric_distribution<uint64_t> d;

  uint64_t _tillNextAlloc;
  uint64_t _countdownAlloc;  /// the number of frees since the last sample interval

  std::unordered_map<void *, uint64_t> _allocSize;
  
  void resetAlloc() {
    // Generate a new sample from the exponential distribution.
    _countdownAlloc = d(gen);
    _tillNextAlloc = _countdownAlloc;
  }
};
