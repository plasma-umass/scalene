#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <signal.h>
#include "common.hpp"

template <class SuperHeap, unsigned long Bytes = 128 * 1024>
class SampleHeap : public SuperHeap {
public:

  SampleHeap()
    : _mallocs (0),
      _frees (0)
  {
    // Ignore the signal until it's been replaced by a client.
    signal(SIGVTALRM, SIG_IGN);
  }

  void * malloc(size_t sz) {
    auto ptr = SuperHeap::malloc(sz);
    _mallocs += SuperHeap::getSize(ptr);
    if (_mallocs - _frees > Bytes) {
      // Raise a signal.
      //	tprintf::tprintf("freed memory = @\n", SuperHeap::freedMemory());
      raise(SIGVTALRM);
      _mallocs = 0;
      _frees = 0;
    }
    //    tprintf::tprintf("SampleHeap::malloc(@) = @\n", sz, ptr);
    return ptr;
  }

  void free(void * ptr) {
    //    tprintf::tprintf("SampleHeap::free @\n", ptr);
    auto sz = SuperHeap::getSize(ptr);
    if (sz > 0) {
      _frees += sz;
      SuperHeap::free(ptr);
    }
  }
  
private:
  unsigned long _mallocs;
  unsigned long _frees;
};

#endif
