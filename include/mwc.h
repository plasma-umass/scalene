// -*- C++ -*-

#ifndef _MWC_H_
#define _MWC_H_

#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

#include <iostream>

#include "common.hpp"
#define d_assert assert

/**
 * @class MWC
 * @brief A super-fast multiply-with-carry pseudo-random number generator due to
 * Marsaglia.
 * @author Emery Berger <http://www.emeryberger.com>
 * @note   Copyright (C) 2005-2020 by Emery Berger.
 */

class MWC {
 public:
  MWC()
      : MWC((getpid() + time(nullptr)) | 1,
            (uint32_t)((uint64_t)pthread_self() | 1)) {}
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
    return min + next() % range;
    // adapted from
    // https://lemire.me/blog/2016/06/27/a-fast-alternative-to-the-modulo-reduction/
    // return min + (((uint64_t)(uint32_t)next() * (uint64_t)range) >> 32);
  }

  // Returns a float between 0 and 1.
  auto inline nextU() {
    auto next_u = (double)next() / (double)UINT32_MAX;
    return next_u;
  }

  // Convert a uniform random number (u) into a geometrically-distributed one
  // with probability p.
  auto inline ATTRIBUTE_ALWAYS_INLINE geometric(double p) {
    auto u = nextU();
    auto geom = (int64_t)round(log(u) / log(1.0 - p));
    return geom;
  }

 private:
  uint32_t z;
  uint32_t w;
};

#endif
