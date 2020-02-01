#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <random>
#include <atomic>

#include <signal.h>
#include "common.hpp"
#include "tprintf.h"
#include "repoman.hpp"

#define DISABLE_SIGNALS 0 // For debugging purposes only.

#if DISABLE_SIGNALS
#define raise(x)
#endif


#define USE_ATOMICS 0

#if USE_ATOMICS
typedef std::atomic<long> counterType;
#else
typedef long counterType;
#endif


template <long TimerInterval>
class MallocTimer {
public:

  MallocTimer()
    : _mallocOps(0)
  {
  }
  
  inline bool registerMalloc(size_t sz) {
    _mallocOps += sz;
    if (unlikely(_mallocOps >= TimerInterval)) {
      _mallocOps -= TimerInterval;
      // _mallocOps = 0; // -= TimerInterval;
      return true;
    } else {
      return false;
    }
  }
  inline constexpr bool registerFree(size_t sz) {
    return false;
  }
  
private:
  counterType _mallocOps;
 
};



template <long TimerInterval>
class FreeTimer {
public:

  FreeTimer()
    : _freeOps(0)
  {
  }
  
  inline constexpr bool registerMalloc(size_t sz) {
    return false;
  }
  
  inline bool registerFree(size_t sz) {
    _freeOps += sz;
    if (unlikely(_freeOps >= TimerInterval)) {
      _freeOps -= TimerInterval;
      // _freeOps = 0; // -= TimerInterval;
      return true;
    } else {
      return false;
    }
  }
  
private:
  counterType _freeOps;
};


template <long MallocSamplingRateBytes, long FreeSamplingRateBytes, class SuperHeap> 
class SampleHeap : public SuperHeap {
private:

  MallocTimer<MallocSamplingRateBytes> mallocTimer;
  FreeTimer<FreeSamplingRateBytes>     freeTimer;

public:

  enum { Alignment = SuperHeap::Alignment };
  enum { MallocSignal = SIGXCPU };
  enum { FreeSignal = SIGPROF }; // SIGVTALRM };
  
  SampleHeap()
  {
    // Ignore the signals until they are replaced by a client.
    signal(MallocSignal, SIG_IGN);
    signal(FreeSignal, SIG_IGN);
  }

  ATTRIBUTE_ALWAYS_INLINE inline void * malloc(size_t sz) {
    // auto realSize = SuperHeap::roundUp(sz, SuperHeap::MULTIPLE); // // SuperHeap::getSize(ptr);
    //    assert((sz < 16) || (realSize <= sz + 15));
    auto ptr = SuperHeap::malloc(sz);
    if (likely(ptr != nullptr)) {
      auto realSize = SuperHeap::getSize(ptr);
      assert(realSize >= sz);
      assert((sz < 16) || (realSize <= 2 * sz));
      if (unlikely(mallocTimer.registerMalloc(realSize))) {
	raise(MallocSignal);
      }
#if 1
      if (unlikely(freeTimer.registerMalloc(realSize))) {
	raise(FreeSignal);
      }
#endif
    }
    return ptr;
  }

  ATTRIBUTE_ALWAYS_INLINE inline void free(void * ptr) {
    if (unlikely(ptr == nullptr)) { return; }
    //    auto sz = SuperHeap::getSize(ptr);
    // if (likely(sz > 0)) {
      auto sz = SuperHeap::free(ptr);
#if 1
      if (unlikely(mallocTimer.registerFree(sz))) {
	raise(MallocSignal);
      }
#endif
      if (unlikely(freeTimer.registerFree(sz))) {
	raise(FreeSignal);
      }
  }
};

#endif
