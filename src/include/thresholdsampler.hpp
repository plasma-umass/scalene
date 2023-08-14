#pragma once
#include <unistd.h>

#include <random>

/**
 * @brief "triggers" samples periodically when |increments-decrements| >
 * SAMPLE_INTERVAL
 *
 */

#define PRINT_STATS 0

class ThresholdSampler {
 public:
  /**
   * @brief Construct a new ThresholdSampler object
   *
   */
  ThresholdSampler(uint64_t SAMPLE_INTERVAL)
      : _sampleInterval(SAMPLE_INTERVAL), allocs(0), frees(0) {
    reset();
  }

  /**
   * @brief decrement by the sample amount, triggering an interval reset when we
   * cross the threshold
   *
   * @param sample the amount to decrement the sample interval by
   * @return bool true iff sampled
   */
  inline bool decrement(uint64_t sample, void*, size_t& ret) {
    _decrements += sample;
    if (unlikely(_decrements >= _increments + _sampleInterval)) {
#if PRINT_STATS
      printf_("[%d] DEALLOC DECREMENT: %lu, %lu -> %lu\n", getpid(),
              _decrements, _increments, _decrements - _increments);
#endif
      ret = _decrements - _increments;
      reset();
      frees += ret;
      return true;
    }
    return false;
  }

  /**
   * @brief increment by the sample amount, triggering an interval reset when we
   * cross the threshold
   *
   * @param sample the amount to decrement the sample interval by
   * @return bool true iff sampled
   */
  inline bool increment(uint64_t sample, void*, size_t& ret) {
    _increments += sample;
    if (unlikely(_increments >= _decrements + _sampleInterval)) {
      ret = _increments - _decrements;
#if PRINT_STATS
      printf_("[%d] ALLOC INCREMENT: %lu, %lu -> %lu\n", getpid(), _decrements,
              _increments, _increments - _decrements);
#endif
      reset();
      allocs += ret;
      return true;
    }
    return false;
  }

 private:
  void reset() {
    _increments = 0;
    _decrements = 0;
#if PRINT_STATS
    printf_("FOOTPRINT = %lu\n", allocs - frees);
#endif
  }

  const uint64_t _sampleInterval;  /// the current sample interval
  uint64_t _increments;  /// the number of increments since the last sample
                         /// interval reset
  uint64_t _decrements;  /// the number of decrements since the last sample
                         /// interval reset
  uint64_t allocs;
  uint64_t frees;
};
