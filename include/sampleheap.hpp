#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <signal.h>
#include "common.hpp"
#include "tprintf.h"

template <class SuperHeap, unsigned long Bytes = 128 * 1024>
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
    if (sz == 0) { sz = 1; } // FIXME POSSIBLY NOT NEEDED.
    auto ptr = SuperHeap::malloc(sz);
    _mallocs += SuperHeap::getSize(ptr);
    if (_mallocs >= Bytes) {
      // Raise a signal.
      //      tprintf::tprintf("signal!\n");
      ///      tprintf::tprintf("SampleHeap::malloc(@) = @\n", SuperHeap::getSize(ptr), ptr);
      raise(SIGVTALRM);
      // _mallocs -= Bytes;
      _mallocs = 0; // -= Bytes;
    }
    return ptr;
  }

  __attribute__((always_inline)) inline void free(void * ptr) {
    if (ptr == nullptr) { return; } // FIXME POSSIBLY NOT NEEDED.
    auto sz = SuperHeap::getSize(ptr);
    if (sz > 0) {
      _frees += sz;
      SuperHeap::free(ptr);
      if (_frees >= Bytes) {
	///	tprintf::tprintf("SampleHeap::free @\n", ptr);
	raise(SIGXCPU);
	// _frees -= Bytes;
	_frees = 0; // -= Bytes;
      }
    }
  }
  
private:
  unsigned long _mallocs;
  unsigned long _frees;
};

#endif
