// Size class calculator
// Dynamic arrays

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


static volatile bool initialized = false;
class TheCustomHeap;
static TheCustomHeap * theCustomHeap = nullptr;

// class TheCustomHeap : public SampleHeap<CheapHeap<400000, 128UL * 1048576UL>> {
class TheCustomHeap : public SampleHeap<CheapHeap<4 * 32768, 128UL * 1048576UL>> {
public:
  TheCustomHeap() {
    theCustomHeap = this;
    initialized = true;
  }
};

TheCustomHeap& getTheCustomHeap() {
  static TheCustomHeap thang;
  return thang;
}

extern "C" __attribute__((constructor)) void xxinit() {
  theCustomHeap = &getTheCustomHeap();
}

extern "C" void * xxmalloc(size_t sz) {
  //  if (initialized) {
  //    return theCustomHeap->malloc(sz);
  // }
  return getTheCustomHeap().malloc(sz);
  // return theCustomHeap->malloc(sz);
}

extern "C" void xxfree(void * ptr) {
  theCustomHeap->free(ptr);
}

extern "C" void xxfree_sized(void * ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  theCustomHeap->free(ptr);
}

extern "C" size_t xxmalloc_usable_size(void * ptr) {
  return theCustomHeap->getSize(ptr); // TODO FIXME adjust for ptr offset?
}

extern "C" bool isMultiThreaded = true;

extern "C" void xxmalloc_lock() {
}

extern "C" void xxmalloc_unlock() {
}

#if 0
int main()
{
  CheapHeap<65536> thang;
  DynArray<unsigned long> arr;
  Stack<unsigned long> stk;
  for (int j = 0; j < 100000; j++) {
    void * buf[10000];
    for (int i = 0; i < 10000; i++) {
      //      buf[i] = thang.malloc(8);
      buf[i] = malloc(8);
    }
    for (int i = 0; i < 10000; i++) {
      // thang.free(buf[i]);
      free(buf[i]);
    }
  }
  
  cout << "DUDE." << endl;
  return 0;
}
#endif
