#pragma once
#include <_types/_uint64_t.h>
#include <random>

/**
 * @brief "triggers" samples periodically when |increments-decrements| >
 * SAMPLE_INTERVAL
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
    resetFree();
  }

  /**
   * @brief decrement by the sample amount, triggering an interval reset when we
   * cross the threshold
   *
   * @param sample the amount to decrement the sample interval by
   * @return uint64_t the previous sample interval if we crossed it; 0 otherwise
   */
  inline uint64_t decrement(uint64_t sample) {
    return increment(sample);
    
    if (unlikely(sample > _tillNextFree)) {
      auto prev = _countdownFree;
      auto diff = sample - _tillNextFree;
      resetFree();
      return prev + diff;
    }
    _tillNextFree -= sample;
    return 0;
  }

  /**
   * @brief increment by the sample amount, triggering an interval reset when we
   * cross the threshold
   *
   * @param sample the amount to decrement the sample interval by
   * @return uint64_t the previous sample interval if we crossed it; 0 otherwise
   */
  inline uint64_t increment(uint64_t sample) {
    if (unlikely(sample > _tillNextAlloc)) {
      auto prev = _countdownAlloc;
      auto diff = sample - _tillNextAlloc;
      resetAlloc();
      return prev + diff;
    }
    _tillNextAlloc -= sample;
    return 0;
  }

 private:

  std::random_device rd;
  std::mt19937 gen;
  std::exponential_distribution<float> d;

  uint64_t _tillNextFree;
  uint64_t _countdownFree;  /// the current countdown to the next sample interval
  uint64_t _tillNextAlloc;
  uint64_t _countdownAlloc;  /// the number of frees since the last sample interval

  void resetFree() {
    // Generate a new sample from the exponential distribution.
    _countdownFree = d(gen);
    _tillNextFree = _countdownFree;
    printf_("RESET FREE %lu\n", _countdownFree);
  }
  
  void resetAlloc() {
    // Generate a new sample from the exponential distribution.
    _countdownAlloc = d(gen);
    _tillNextAlloc = _countdownAlloc;
    printf_("RESET ALLOC %lu\n", _countdownAlloc);
  }
};
