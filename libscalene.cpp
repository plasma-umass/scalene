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

class TheCustomHeap;
static TheCustomHeap * theCustomHeap = nullptr;

const auto MallocSamplingRate = 256 * 1024 * 1024;
const auto FreeSamplingRate   = 256 * 1024 * 1024;
const auto RepoSize = 4096;

typedef SampleHeap<MallocSamplingRate, FreeSamplingRate, RepoMan<RepoSize>> CustomHeapType;
//typedef SampleHeap<MallocSamplingRate, FreeSamplingRate, RepoMan<RepoSize>> CustomHeapType;

class TheCustomHeap : public CustomHeapType {
  typedef CustomHeapType Super;
public:
  TheCustomHeap() {
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
