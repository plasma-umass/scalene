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
const auto MallocSamplingRate = 1048583; // 33554467; // 16777259; // 1048583; // 1 * 1024 * 1024;
const auto FreeSamplingRate   = 1048589; // 16777289; // 1048589; // 1 * 1024 * 1024;
const auto RepoSize = 4096;

typedef SampleHeap<MallocSamplingRate, FreeSamplingRate, RepoMan<RepoSize>> CustomHeapType;

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

extern "C" ATTRIBUTE_EXPORT void * xxmalloc(size_t sz) {
  void * ptr = nullptr;
  if (theCustomHeap) {
    ptr = theCustomHeap->malloc(sz);
  } else {
    ptr = getTheCustomHeap().malloc(sz);
  }
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT void xxfree(void * ptr) {
  theCustomHeap->free(ptr);
}

extern "C" ATTRIBUTE_EXPORT void xxfree_sized(void * ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  getTheCustomHeap().free(ptr);
}

extern "C" ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void * ptr) {
  return theCustomHeap->getSize(ptr); // TODO FIXME adjust for ptr offset?
}

extern "C" ATTRIBUTE_EXPORT void xxmalloc_lock() {
}

extern "C" ATTRIBUTE_EXPORT void xxmalloc_unlock() {
}
