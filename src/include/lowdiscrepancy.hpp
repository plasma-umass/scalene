#pragma once

#include <unistd.h>

#include <chrono>
#include <cmath>
#include <iostream>
#include <random>
#include <thread>

/** generator for low-discrepancy sequences **/

class LowDiscrepancy {
 private:
  uint64_t _next;

 public:
  LowDiscrepancy(uint64_t seed) {
    std::mt19937_64 rng(seed);
    rng();  // consume one RNG
    // Initialize the sequence with a value that's in the middle two quartiles.
    while ((_next < UINT64_MAX / 4) || (_next > UINT64_MAX - UINT64_MAX / 4)) {
      _next = rng();  //  / (float) rng.max();
    }
  }

  static inline constexpr uint64_t min() { return 0; }
  static inline constexpr uint64_t max() { return UINT64_MAX; }

 private:
  static inline constexpr auto next() {
    return (uint64_t)(
        (double)UINT64_MAX *
        0.6180339887498949025257388711906969547271728515625L);  // 1 - golden
                                                                // ratio
  }

 public:
  inline auto operator()() {
    auto prev = _next;
    _next = _next + next();
#if 0
    if (_next > 1.0) {
      _next = _next - 1.0;
    }
#endif
    return prev;
  }

  void discard() { (*this)(); }
};
