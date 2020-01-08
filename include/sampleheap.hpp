#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <signal.h>
#include "common.hpp"
#include "tprintf.h"

template <unsigned long SamplingRateBytes, class SuperHeap> 
class SampleHeap : public SuperHeap {
public:

  SampleHeap()
    : _mallocs (0),
      _frees (0)
  {
    // Ignore the signal until it's been replaced by a client.
    signal(SIGVTALRM, SIG_IGN);
    signal(SIGXCPU, SIG_IGN);
  }

  ATTRIBUTE_ALWAYS_INLINE inline void * malloc(size_t sz) {
    // Need to handle zero-size requests.
    //    if (sz == 0) { sz = sizeof(double); }
    auto ptr = SuperHeap::malloc(sz);
    _mallocs += sz; /// SuperHeap::getSize(ptr);
    if (unlikely(_mallocs >= SamplingRateBytes)) {
      // Raise a signal.
      //      tprintf::tprintf("signal!\n");
      // tprintf::tprintf("SampleHeap::malloc(@) = @\n", SuperHeap::getSize(ptr), ptr);
      raise(SIGVTALRM);
      // _mallocs -= SamplingRateBytes;
      _mallocs = 0; // -= SamplingRateBytes;
    }
    return ptr;
  }

  ATTRIBUTE_ALWAYS_INLINE inline void free(void * ptr) {
    // Need to drop free(0).
    //    if (ptr == nullptr) { return; }
    auto sz = SuperHeap::free(ptr); // SuperHeap::getSize(ptr);
    _frees += sz;
    if (unlikely(_frees >= SamplingRateBytes)) {
      // tprintf::tprintf("SampleHeap::free @ = @\n", ptr, sz);
      raise(SIGXCPU);
      // _frees -= SamplingRateBytes;
      _frees = 0; // -= SamplingRateBytes;
    }
  }
  
private:
  unsigned long _mallocs;
  unsigned long _frees;
};

#endif
