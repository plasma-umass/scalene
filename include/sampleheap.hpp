#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <random>
#include <atomic>

#include <signal.h>
#include "common.hpp"
#include "tprintf.h"
#include "repoman.hpp"

#define USE_ORIGINAL_SIGNALS 1
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
    if (unlikely(_mallocOps > TimerInterval)) {
      _mallocOps = 0;
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
    : _mallocOps(0)
  {
  }
  
  inline constexpr bool registerMalloc(size_t sz) {
    return false;
  }
  
  inline bool registerFree(size_t sz) {
    _mallocOps += sz;
    if (unlikely(_mallocOps > TimerInterval)) {
      _mallocOps = 0;
      return true;
    } else {
      return false;
    }
  }
  
private:
  counterType _mallocOps;
};


#if 0
template <long TimerInterval>
class MemoryGrowthTimer {
public:

  MemoryGrowthTimer()
    : _mallocOps(0),
      _freeOps(0),
      _maxOps(0),
      _engine(1), // Fixed seed for determinism's sake.
      _uniform_dist(TimerInterval / 2, (TimerInterval * 3) / 2),
      _nextInterval(TimerInterval)
  {
  }
  inline bool registerMalloc(size_t sz) {
    _mallocOps += sz;
    if (_mallocOps - _freeOps > _maxOps + _nextInterval) { // TimerInterval) { // _nextInterval) {
      // auto diff = (_mallocOps - _freeOps) - _maxOps;
      _maxOps = _mallocOps - _freeOps;
      //      tprintf::tprintf("mallocops = @, freeops = @, new max = @, interval was @\n", _mallocOps, _freeOps, _maxOps, _nextInterval);
      _nextInterval = _uniform_dist(_engine);
      return true;
    }
    return false;
  }
  inline bool registerFree(size_t sz) {
    _freeOps += sz;
    return false;
  }
  
private:
  //  std::random_device _r;
  std::default_random_engine _engine;
  std::uniform_int_distribution<long> _uniform_dist;
  long _mallocOps;
  long _freeOps;
  long _maxOps;
  long _nextInterval;
};
#endif


#define DISABLE_SIGNALS 0 // For debugging purposes only.

#if DISABLE_SIGNALS
#define raise(x)
#endif


template <long MallocSamplingRateBytes, long FreeSamplingRateBytes, class SuperHeap> 
class SampleHeap : public SuperHeap {
private:

  MallocTimer<MallocSamplingRateBytes> mallocTimer;
  FreeTimer<FreeSamplingRateBytes>     freeTimer;

public:

  enum { Alignment = SuperHeap::Alignment };
  enum { FreeSignal = SIGPROF }; // SIGVTALRM };
  enum { MallocSignal = SIGXCPU };
  
  SampleHeap()
  {
    // Ignore the signals until they are replaced by a client.
    signal(FreeSignal, SIG_IGN);
    signal(MallocSignal, SIG_IGN);
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
	//	tprintf::tprintf("[M @]", realSize);
	raise(MallocSignal);
      }
#if 0
      if (freeTimer.registerMalloc(realSize)) {
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
#if 0
      if (mallocTimer.registerFree(sz)) {
	//	tprintf::tprintf("[F @]", sz);
	raise(MallocSignal);
      }
#endif
      if (unlikely(freeTimer.registerFree(sz))) {
	raise(FreeSignal);
      }
      //    }
  }
};

#endif
