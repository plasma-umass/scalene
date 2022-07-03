#pragma once

#if !defined(_WIN32)
#include <pthread.h>
#include <unistd.h>
#endif

#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <thread>

#include "common.hpp"
#include "printf.h"

#define SAMPLER_DETERMINISTIC 0
#define SAMPLER_LOWDISCREPANCY 0

#include <stdio.h>
#include <time.h>

#if SAMPLER_LOWDISCREPANCY
#include "lowdiscrepancy.hpp"
#endif

template <uint64_t SAMPLE_RATE>
class Sampler {
 private:
  static constexpr double SAMPLE_PROBABILITY =
      (double)1.0 / (double)SAMPLE_RATE;

  uint64_t _next;
#if !SAMPLER_DETERMINISTIC
#if !SAMPLER_LOWDISCREPANCY
  std::mt19937_64 rng{1234567890UL + (uint64_t)getpid() + (uint64_t)this +
                      (uint64_t)pthread_self()};
#else
  LowDiscrepancy rng{1};  // 234567890UL + (uint64_t)getpid() + (uint64_t)this +
                          // (uint64_t)pthread_self()};
#endif
#endif

  std::geometric_distribution<uint64_t> geom{SAMPLE_PROBABILITY};

 public:
  Sampler() {
#if !SAMPLER_DETERMINISTIC
    while (true) {
      _next = geom(rng);
      if (_next != 0) {
        break;
      }
    }
#else
    _next = SAMPLE_RATE;
#endif
  }

  inline ATTRIBUTE_ALWAYS_INLINE void unsample(uint64_t sz) {
    if (_next < SAMPLE_RATE / 2) {
      _next += sz;
    }
  }

  inline ATTRIBUTE_ALWAYS_INLINE uint64_t sample(uint64_t sz) {
    if (unlikely(_next <= sz)) {
      // return updateSample(sz - _next);
      return updateSample(sz);
    }
    assert(sz < _next);
    _next -= sz;
    return 0;
  }

  uint64_t updateSample(uint64_t sz) {
#if SAMPLER_DETERMINISTIC
    _next = SAMPLE_RATE;
#else
    while (true) {
      _next = geom(rng);
      if (_next != 0) {
        break;
      }
    }
#endif
    if (sz >= SAMPLE_RATE) {
      return sz;
    }
    return SAMPLE_RATE;
  }
};
