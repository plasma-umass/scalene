#pragma once

#include <cmath>
#include <iostream>
#include <thread>
#include <unistd.h>

#include <chrono>
#include <random>

/** generator for low-discrepancy sequences **/

class LowDiscrepancy {
  
private:

  uint64_t _next;

public:

  LowDiscrepancy(uint64_t seed)
  {
    std::mt19937_64 rng (seed);
    rng(); // consume one RNG
    _next = rng(); //  / (float) rng.max();
  }

  static inline constexpr uint64_t min() { return 0; }
  static inline constexpr uint64_t max() { return UINT64_MAX; }

private:
  static inline constexpr auto next() {
    return (uint64_t) ((double) UINT64_MAX * 0.6180339887498949025257388711906969547271728515625L); // 1 - golden ratio
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
    std::cout << prev << std::endl;
    return prev;
  }

  void discard() {
    (*this)();
  }
};
