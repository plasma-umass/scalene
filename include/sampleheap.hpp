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

  __attribute__((always_inline)) inline void * malloc(size_t sz) {
    // Need to handle zero-size requests.
    if (sz == 0) { sz = sizeof(double); }
    auto ptr = SuperHeap::malloc(sz);
    _mallocs += SuperHeap::getSize(ptr);
    if (_mallocs >= SamplingRateBytes) {
      // Raise a signal.
      //      tprintf::tprintf("signal!\n");
      // tprintf::tprintf("SampleHeap::malloc(@) = @\n", SuperHeap::getSize(ptr), ptr);
      raise(SIGVTALRM);
      // _mallocs -= SamplingRateBytes;
      _mallocs = 0; // -= SamplingRateBytes;
    }
    return ptr;
  }

  __attribute__((always_inline)) inline void free(void * ptr) {
    // Need to drop free(0).
    if (ptr == nullptr) { return; }
    auto sz = SuperHeap::getSize(ptr);
    if (sz > 0) {
      _frees += sz;
      SuperHeap::free(ptr);
      if (_frees >= SamplingRateBytes) {
	// tprintf::tprintf("SampleHeap::free @ = @\n", ptr, sz);
	raise(SIGXCPU);
	// _frees -= SamplingRateBytes;
	_frees = 0; // -= SamplingRateBytes;
      }
    }
  }
  
private:
  unsigned long _mallocs;
  unsigned long _frees;
};

#endif
