#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h> // for getpid()

#include <random>
#include <atomic>

#include <signal.h>
#include "common.hpp"
#include "tprintf.h"
#include "repoman.hpp"

// Max pid length = 7 digits.
const auto flags = O_WRONLY | O_CREAT | O_SYNC | O_APPEND; // O_TRUNC;
const auto perms = S_IRUSR | S_IWUSR;
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

class AllocationTimer {
public:
  // Note: for now, we don't multiply the intervals.
  static constexpr auto Multiplier = 1;
};


template <unsigned long MallocSamplingRateBytes, class SuperHeap> 
class SampleHeap : public SuperHeap {
public:

  enum { Alignment = SuperHeap::Alignment };
  enum { MallocSignal = SIGXCPU };
  enum { FreeSignal = SIGPROF }; // SIGVTALRM };
  
  SampleHeap()
    : _interval (MallocSamplingRateBytes),
      _mallocOps (0),
      _freeOps (0),
      _mallocTriggered (0),
      _freeTriggered (0)
  {
    // Ignore these signals until they are replaced by a client.
    signal(MallocSignal, SIG_IGN);
    signal(FreeSignal, SIG_IGN);
    // Fill the 0s with the pid.
    auto pid = getpid();
    sprintf(scalene_malloc_signal_filename, "/tmp/scalene-malloc-signal%d", pid);
    sprintf(scalene_free_signal_filename, "/tmp/scalene-malloc-signal%d", pid);
  }

  ~SampleHeap() {
    // Delete the signal log files.
    unlink(scalene_malloc_signal_filename);
    unlink(scalene_free_signal_filename);
  }
  
  ATTRIBUTE_ALWAYS_INLINE inline void * malloc(size_t sz) {
    auto ptr = SuperHeap::malloc(sz);
    if (likely(ptr != nullptr)) {
      auto realSize = SuperHeap::getSize(ptr);
      assert(realSize >= sz);
      assert((sz < 16) || (realSize <= 2 * sz));
      _mallocOps += realSize;
      if (unlikely(_mallocOps >= _interval)) {
	writeCount(scalene_malloc_signal_filename, _mallocOps);
	_mallocTriggered++;
	_mallocOps = 0;
	if (_mallocTriggered == _freeTriggered) {
	  _interval = (unsigned long) (_interval * AllocationTimer::Multiplier);
	}
	raise(MallocSignal);
      }
    }
    return ptr;
  }

  ATTRIBUTE_ALWAYS_INLINE inline void free(void * ptr) {
    if (unlikely(ptr == nullptr)) { return; }
    auto realSize = SuperHeap::free(ptr);
    
    _freeOps += realSize;
    if (unlikely(_freeOps >= _interval)) {
      writeCount(scalene_free_signal_filename, _freeOps);
      _freeTriggered++;
      _freeOps = 0;
      if (_mallocTriggered == _freeTriggered) {
	_interval = (unsigned long) (_interval * AllocationTimer::Multiplier);
      }
      raise(FreeSignal);
    }
  }

private:

  void writeCount(const char * fname, unsigned long count) {
    char buf[255];
    sprintf(buf, "%lu\n", count);
    int fd = open(fname, flags, perms);
    write(fd, buf, strlen(buf));
    close(fd);
  }

  counterType _mallocOps;
  counterType _freeOps;
  char scalene_malloc_signal_filename[255];
  char scalene_free_signal_filename[255];
  unsigned long _mallocTriggered;
  unsigned long _freeTriggered;
  unsigned long _interval;
  
};

#endif
