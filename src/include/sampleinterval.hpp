#pragma once
#include <random>

/**
 * @brief "triggers" samples periodically when |increments-decrements| >
 * SAMPLE_INTERVAL
 *
 */

class SampleInterval {
 public:
  /**
   * @brief Construct a new SampleInterval object
   *
   */
  SampleInterval(uint64_t SAMPLE_INTERVAL) : _sampleInterval(SAMPLE_INTERVAL) {
    reset();
  }

  /**
   * @brief decrement by the sample amount, triggering an interval reset when we
   * cross the threshold
   *
   * @param sample the amount to decrement the sample interval by
   * @return uint64_t the previous sample interval if we crossed it; 0 otherwise
   */
  inline uint64_t decrement(uint64_t sample) {
    _decrements += sample;
    if (unlikely(_decrements >= _increments + _sampleInterval)) {
      auto ret = _decrements - _increments;
      reset();
      return ret;
    }
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
    _increments += sample;
    if (unlikely(_increments >= _decrements + _sampleInterval)) {
      auto ret = _increments - _decrements;
      reset();
      return ret;
    }
    return 0;
  }

 private:
  void reset() {
    _increments = 0;
    _decrements = 0;
  }

  const uint64_t _sampleInterval;  /// the current sample interval
  uint64_t _increments;  /// the number of increments since the last sample
                         /// interval reset
  uint64_t _decrements;  /// the number of decrements since the last sample
                         /// interval reset
};
