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
const auto flags = O_WRONLY | O_CREAT | O_SYNC | O_APPEND; // O_TRUNC;
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
  
  inline double registerMalloc(size_t sz) {
    _mallocOps += sz;
    if (unlikely(_mallocOps >= TimerInterval)) {
      double count = _mallocOps / (double) TimerInterval;
      _mallocOps = 0;
      return count;
    } else {
      return 0;
    }
  }
  inline constexpr double registerFree(size_t sz);
  
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
  
  inline constexpr double registerMalloc(size_t sz);
  
  inline double registerFree(size_t sz) {
    _freeOps += sz;
    if (unlikely(_freeOps >= TimerInterval)) {
      double count = _freeOps / (double) TimerInterval;
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
      double count = 0.0;
      
      if (unlikely(count = mallocTimer.registerMalloc(realSize))) {
	char buf[255];
	sprintf(buf, "%f\n", count);
	mallocFd = open(scalene_malloc_signal_filename, flags, S_IRUSR | S_IWUSR);
	write(mallocFd, buf, strlen(buf));
	close(mallocFd);
	raise(MallocSignal);
      }
    }
    return ptr;
  }

  ATTRIBUTE_ALWAYS_INLINE inline void free(void * ptr) {
    if (unlikely(ptr == nullptr)) { return; }
    //    auto sz = SuperHeap::getSize(ptr);
    // if (likely(sz > 0)) {
      auto realSize = SuperHeap::free(ptr);
      
      double count = 0;
      if (unlikely(count = freeTimer.registerFree(realSize))) {
	char buf[255];
	sprintf(buf, "%f\n", count);
	freeFd = open(scalene_free_signal_filename, flags, S_IRUSR | S_IWUSR);
	write(freeFd, buf, strlen(buf));
	close(freeFd);
	raise(FreeSignal);
      }
  }
};

#endif
