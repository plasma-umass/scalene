#ifndef CLASSWARFARE_H
#define CLASSWARFARE_H

#include <stdlib.h>
#include "ilog2.h"
#include "common.hpp"

template <unsigned long Multiple = 8>
class ClassWarfare {
public:

  enum { THRESHOLD_SIZE = 512 };
  enum { THRESHOLD_SIZECLASS = THRESHOLD_SIZE / Multiple - 1 };

  inline static constexpr int getSizeClass(const size_t sz) {
    auto rounded = (sz + (Multiple - 1)) & ~(Multiple - 1);
    unsigned long sizeClass = 0;
    if (likely(sz <= THRESHOLD_SIZE)) {
      sizeClass = rounded / Multiple - 1;
    } else {
      sizeClass = THRESHOLD_SIZECLASS + HL::ilog2(rounded) - HL::ilog2(THRESHOLD_SIZE);
    }
    return sizeClass;
  }
  
  enum { MAX_SIZECLASS = getSizeClass(4 * 1024UL * 1048576UL) };

  inline static void constexpr getSizeAndClass(const size_t sz, size_t& realSize, int& sizeClass) {
    if (likely(sz <= THRESHOLD_SIZE)) {
      realSize = (sz + (Multiple - 1)) & ~(Multiple - 1);
      sizeClass = realSize / Multiple - 1;
    } else {
      auto log_size = HL::ilog2(sz);
      sizeClass = THRESHOLD_SIZECLASS + log_size - HL::ilog2(THRESHOLD_SIZE);
      realSize = (1 << log_size);
    }
  }

  inline static constexpr void getSizeFromClass(const int sizeClass, size_t& sz) {
    if (likely(sizeClass <= THRESHOLD_SIZECLASS)) {
      sz = (sizeClass + 1) * Multiple;
    } else {
      sz = THRESHOLD_SIZE * (1 << (sizeClass - THRESHOLD_SIZECLASS));
    }
  }
};

#endif
