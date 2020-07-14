// -*- C++ -*-

#ifndef _MWC_H_
#define _MWC_H_

#include <stdio.h>
#include <iostream>

#include "common.hpp"
#include <assert.h>
#define d_assert assert

/**
 * @class MWC
 * @brief A super-fast multiply-with-carry pseudo-random number generator due to Marsaglia.
 * @author Emery Berger <http://www.emeryberger.com>
 * @note   Copyright (C) 2005-2020 by Emery Berger.
 */

class MWC {
public:
  
  MWC(uint32_t seed1, uint32_t seed2) : z(seed1), w(seed2) {
    d_assert(seed1 != 0);
    d_assert(seed2 != 0);
    // debug("MWC seed1: %u seed2: %u\n", seed1, seed2);
  }

  inline uint32_t ATTRIBUTE_ALWAYS_INLINE next() {
    d_assert(w != 0);
    d_assert(z != 0);
    // These magic numbers are derived from a note by George Marsaglia.
    uint32_t znew = 36969 * (z & 65535) + (z >> 16);
    uint32_t wnew = 18000 * (w & 65535) + (w >> 16);
    uint32_t x = (znew << 16) + wnew;
    // debug("MWC: %8x\n", x);
    d_assert(wnew != 0);
    d_assert(znew != 0);
    w = wnew;
    z = znew;
    return x;
  }

  // returns a number between min and max (inclusive)
  inline uint32_t ATTRIBUTE_ALWAYS_INLINE inRange(size_t min, size_t max) {
    size_t range = 1 + max - min;
    //    return min + next() % range;
    // adapted from https://lemire.me/blog/2016/06/27/a-fast-alternative-to-the-modulo-reduction/
    return min + (((uint64_t)(uint32_t)next() * (uint64_t)range) >> 32);
  }

  // Returns a float between 0 and 1.
  auto inline nextU() {
    return (float) inRange(0, UINT32_MAX) / (float) UINT32_MAX;
  }

  // Convert a uniform random number (u) into a geometrically-distributed one with probability p.
  auto inline ATTRIBUTE_ALWAYS_INLINE geometric(float p) {
    auto u = nextU();
    return (int) round(log(u) / log(1.0 - p));
  }

private:
  uint32_t z;
  uint32_t w;
};


#endif
