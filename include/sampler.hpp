#pragma once

#include <cmath>
#include <iostream>
#include <thread>
#include <unistd.h>

#include "mwc.h"

#define SAMPLER_DETERMINISTIC 0

template <int SAMPLE_RATE>
class Sampler {
private:
  int32_t _next;
#if !SAMPLER_DETERMINISTIC
  MWC rng;
#endif
  
public:
  Sampler()
  {
#if !SAMPLER_DETERMINISTIC
    _next = rng.geometric(SAMPLE_PROBABILITY);
#else
    _next = SAMPLE_RATE;
#endif
  }
  
  inline ATTRIBUTE_ALWAYS_INLINE int sample(size_t sz) {
    _next -= sz;
    if (unlikely(_next <= 0)) {
#if SAMPLER_DETERMINISTIC
      _next = SAMPLE_RATE;
#else
      _next = rng.geometric(SAMPLE_PROBABILITY);
#endif
      if (sz >= SAMPLE_RATE) {
	return sz / SAMPLE_RATE + 1;
      } else {
	return 1;
      }
    }
    return 0;
  }
  
private:
  static constexpr double SAMPLE_PROBABILITY = (double) 1.0 / (double) SAMPLE_RATE;
};
