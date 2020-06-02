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
#include "stprintf.h"
#include "tprintf.h"

#define DISABLE_SIGNALS 0 // FIXME // For debugging purposes only.

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
  enum AllocSignal { MallocSignal = SIGXCPU, FreeSignal = SIGXFSZ };
  enum { CallStackSamplingRate = MallocSamplingRateBytes / 10 };
  
  SampleHeap()
    : _interval (MallocSamplingRateBytes),
      _callStackInterval (CallStackSamplingRate),
      _mallocOps (0),
      _freeOps (0),
      _mallocTriggered (0),
      _freeTriggered (0),
      _pythonCount (0),
      _cCount (0)
  {
    // Ignore these signals until they are replaced by a client.
    signal(MallocSignal, SIG_IGN);
    signal(FreeSignal, SIG_IGN);
    // Fill the 0s with the pid.
    auto pid = getpid();
    stprintf::stprintf(scalene_malloc_signal_filename, "/tmp/scalene-malloc-signal@", pid);
    // scalene_malloc_signal_filename, "/tmp/scalene-malloc-signal%d", pid);
    //    sprintf(scalene_free_signal_filename, "/tmp/scalene-free-signal%d", pid);
  }

  ~SampleHeap() {
    // Delete the signal log files.
    unlink(scalene_malloc_signal_filename);
    //    unlink(scalene_free_signal_filename);
  }
  
  ATTRIBUTE_ALWAYS_INLINE inline void * malloc(size_t sz) {
    auto ptr = SuperHeap::malloc(sz);
    if (likely(ptr != nullptr)) {
      auto realSize = SuperHeap::getSize(ptr);
      assert(realSize >= sz);
      assert((sz < 16) || (realSize <= 2 * sz));
      _mallocOps += realSize;
      if (likely(realSize <= _callStackInterval)) {
	_callStackInterval -= realSize;
      } else {
	recordCallStack();
	_callStackInterval = CallStackSamplingRate;
      }
      if (unlikely(_mallocOps >= _interval)) {
	writeCount(MallocSignal, _mallocOps);
	_pythonCount = 0;
	_cCount = 0;
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
      writeCount(FreeSignal, _freeOps);
      _freeTriggered++;
      _freeOps = 0;
      if (_mallocTriggered == _freeTriggered) {
	_interval = (unsigned long) (_interval * AllocationTimer::Multiplier);
      }
      raise(FreeSignal);
    }
  }

private:

  counterType _mallocOps;
  counterType _freeOps;
  char scalene_malloc_signal_filename[255];
  char scalene_free_signal_filename[255];
  unsigned long long _mallocTriggered;
  unsigned long long _freeTriggered;
  unsigned long _interval;
  unsigned long _callStackInterval;
  unsigned long _pythonCount;
  unsigned long _cCount;
  
  void recordCallStack() {
    // Walk the stack to see if this memory was allocated by Python
    // through its object allocation APIs.
    const auto MAX_FRAMES_TO_CHECK = 3; // enough to skip past the replacement_malloc
    void * callstack[MAX_FRAMES_TO_CHECK];
    auto frames = backtrace(callstack, MAX_FRAMES_TO_CHECK);
    for (auto i = 0; i < frames; i++) {
      Dl_info info;
      int r = dladdr(callstack[i], &info);
      if (r) {
	const char * fn_name = info.dli_sname;
	if (fn_name) {
	  if (strlen(fn_name) < 13) { // length of _PyMem_Malloc
	    continue;
	  }
	  if (!((fn_name[0] == '_') && (fn_name[1] == 'P') && (fn_name[2] == 'y'))) {
	    continue;
	  }
	  ///	  tprintf::tprintf("@\n", fn_name);
	  // TBD: realloc requires special handling.
	  // * _PyObject_Realloc
	  // * _PyMem_Realloc
	  if (strstr(fn_name, "_PyObject_") != 0) {
	    if ((strstr(fn_name, "_PyObject_GC_Alloc") != 0) ||
		(strstr(fn_name, "_PyObject_Malloc") != 0) ||
		(strstr(fn_name, "_PyObject_Calloc") != 0))	      
	      {
		_pythonCount++;
		return;
	      }
	  }
	  if (strstr(fn_name, "_PyMem_") != 0) {
	    if ((strstr(fn_name, "_PyMem_Malloc") != 0) ||
		(strstr(fn_name, "_PyMem_Calloc") != 0) ||
		(strstr(fn_name, "_PyMem_RawMalloc") != 0) ||
		(strstr(fn_name, "_PyMem_RawCalloc") != 0))
	      {
		_pythonCount++;
		return;
	      }
	  }
	}
      }
    }
    //    tprintf::tprintf("C");
    _cCount++;
  }
  
  static constexpr auto flags = O_WRONLY | O_CREAT | O_SYNC | O_APPEND; // O_TRUNC;
  static constexpr auto perms = S_IRUSR | S_IWUSR;

  void writeCount(AllocSignal sig, unsigned long count) {
    char buf[255];
    if (_pythonCount == 0) {
      _pythonCount = 1; // prevent 0/0
    }
    stprintf::stprintf(buf, "@,@,@,@\n", ((sig == MallocSignal) ? 'M' : 'F'), _mallocTriggered + _freeTriggered, count, (float) _pythonCount / (_pythonCount + _cCount));
    //    sprintf(buf, "%c,%llu,%lu,%f\n", ((sig == MallocSignal) ? 'M' : 'F'), _mallocTriggered + _freeTriggered, count, (float) _pythonCount / (_pythonCount + _cCount));
    int fd = open(scalene_malloc_signal_filename, flags, perms);
    write(fd, buf, strlen(buf));
    close(fd);
  }

};

#endif
