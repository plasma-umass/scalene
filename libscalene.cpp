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

class TheCustomHeap;
static TheCustomHeap * theCustomHeap = nullptr;

//class TheCustomHeap : public SampleHeap<CheapHeap<256UL * 1048576UL>> {
class TheCustomHeap : public SampleHeap<HL::SizeHeap<CheapHeap<256UL * 1048576UL>>> {
public:
  TheCustomHeap() {
    theCustomHeap = this;
  }
};

TheCustomHeap& getTheCustomHeap() {
  static TheCustomHeap thang;
  return thang;
}

extern "C" void * xxmalloc(size_t sz) {
  if (theCustomHeap) {
    return theCustomHeap->malloc(sz);
  } else {
    return getTheCustomHeap().malloc(sz);
  }
}

extern "C" void xxfree(void * ptr) {
  theCustomHeap->free(ptr);
}

extern "C" void xxfree_sized(void * ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  getTheCustomHeap().free(ptr);
}

extern "C" size_t xxmalloc_usable_size(void * ptr) {
  return theCustomHeap->getSize(ptr); // TODO FIXME adjust for ptr offset?
}

extern "C" void xxmalloc_lock() {
}

extern "C" void xxmalloc_unlock() {
}
