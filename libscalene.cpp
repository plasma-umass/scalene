#include <heaplayers.h>

#include "tprintf.h"
#include "common.hpp"

#include "mmaparray.hpp"
#include "dynarray.hpp"
#include "stack.hpp"
#include "buffer.hpp"
#include "classwarfare.hpp"
#include "bufferbump.hpp"
#include "cheapheap.hpp"
#include "sampleheap.hpp"

#include "repoman.hpp"

#include <stdio.h>
#include <execinfo.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>


class TheCustomHeap;
static TheCustomHeap * theCustomHeap = nullptr;

// We use prime numbers here (near 1MB, for example) to avoid the risk
// of stride behavior interfering with sampling.

//const auto MallocSamplingRate = 1048583;
//const auto MallocSamplingRate = 4194319;
//const auto MallocSamplingRate = 8388617;
const auto MallocSamplingRate = 16777259;
const auto RepoSize = 4096;

typedef SampleHeap<MallocSamplingRate, RepoMan<RepoSize>> CustomHeapType;

class TheCustomHeap : public CustomHeapType {
  typedef CustomHeapType Super;
public:
  TheCustomHeap()
  {
    theCustomHeap = this;
  }
};


TheCustomHeap& getTheCustomHeap() {
  static TheCustomHeap thang;
  return thang;
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void * xxmalloc(size_t sz) {
  void * ptr = nullptr;
  if (theCustomHeap) {
    ptr = theCustomHeap->malloc(sz);
  } else {
    ptr = getTheCustomHeap().malloc(sz);
  }
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxfree(void * ptr) {
  theCustomHeap->free(ptr);
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxfree_sized(void * ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  getTheCustomHeap().free(ptr);
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) size_t xxmalloc_usable_size(void * ptr) {
  return theCustomHeap->getSize(ptr); // TODO FIXME adjust for ptr offset?
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxmalloc_lock() {
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxmalloc_unlock() {
}
