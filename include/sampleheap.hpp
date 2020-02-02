#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>

#include <random>
#include <atomic>

#include <signal.h>
#include "common.hpp"
#include "tprintf.h"
#include "repoman.hpp"


const char scalene_malloc_signal_filename[] = "/tmp/scalene-malloc-signal";
const char scalene_free_signal_filename[]   = "/tmp/scalene-free-signal";
const auto flags = O_WRONLY | O_CREAT | O_SYNC | O_TRUNC;
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
  
  inline int registerMalloc(size_t sz) {
    _mallocOps += sz;
    if (unlikely(_mallocOps >= TimerInterval)) {
      auto count = (_mallocOps + TimerInterval - 1) / TimerInterval;
      _mallocOps = 0;
      return count;
    } else {
      return 0;
    }
  }
  inline constexpr int registerFree(size_t sz) {
    return 0;
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
  
  inline constexpr int registerMalloc(size_t sz) {
    return 0;
  }
  
  inline int registerFree(size_t sz) {
    _freeOps += sz;
    if (unlikely(_freeOps >= TimerInterval)) {
      auto count = (_freeOps + TimerInterval - 1) / TimerInterval;
      _freeOps = 0;
      return count;
    } else {
      return 0;
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
  int mallocFd;
  int freeFd;
  
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

  ~SampleHeap() {
    close(mallocFd);
    close(freeFd);
    unlink(scalene_malloc_signal_filename);
    unlink(scalene_free_signal_filename);
  }
  
  ATTRIBUTE_ALWAYS_INLINE inline void * malloc(size_t sz) {
    // auto realSize = SuperHeap::roundUp(sz, SuperHeap::MULTIPLE); // // SuperHeap::getSize(ptr);
    //    assert((sz < 16) || (realSize <= sz + 15));
    auto ptr = SuperHeap::malloc(sz);
    if (likely(ptr != nullptr)) {
      auto realSize = SuperHeap::getSize(ptr);
      assert(realSize >= sz);
      assert((sz < 16) || (realSize <= 2 * sz));
      int count = 0;
      if (unlikely(count = mallocTimer.registerMalloc(realSize))) {
	//	tprintf::tprintf("malloc SIG @\n", count);
	char buf[255];
	sprintf(buf, "%d\n\n\n", count);
	mallocFd = open(scalene_malloc_signal_filename, flags, S_IRUSR | S_IWUSR);
	write(mallocFd, buf, strlen(buf));
	close(mallocFd);
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
      int count = 0;
      if (unlikely(count = freeTimer.registerFree(sz))) {
	// tprintf::tprintf("free SIG @\n", count);
	char buf[255];
	sprintf(buf, "%d\n", count);
	freeFd = open(scalene_free_signal_filename, flags, S_IRUSR | S_IWUSR);
	write(freeFd, buf, strlen(buf));
	close(freeFd);
	raise(FreeSignal);
      }
  }
};

#endif
