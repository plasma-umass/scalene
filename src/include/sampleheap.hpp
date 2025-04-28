#pragma once

#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <assert.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/errno.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>  // for getpid()

#include <atomic>
#include <random>

// We're unable to use the limited API because, for example,
// there doesn't seem to be a function returning co_filename
// #define Py_LIMITED_API 0x03070000

#include "common.hpp"
#include "mallocrecursionguard.hpp"
#include "poissonsampler.hpp"
#include "printf.h"
#include "pywhere.hpp"
#include "samplefile.hpp"
#include "scaleneheader.hpp"
#include "thresholdsampler.hpp"

static SampleFile& getSampleFile() {
  static SampleFile mallocSampleFile("/tmp/scalene-malloc-signal%d",
                                     "/tmp/scalene-malloc-lock%d",
                                     "/tmp/scalene-malloc-init%d");

  return mallocSampleFile;
}

#define USE_ATOMICS 0
#if USE_ATOMICS
typedef std::atomic<uint64_t> counterType;
#else
typedef uint64_t counterType;
#endif

template <uint64_t DefaultAllocationSamplingRateBytes, class SuperHeap>
class SampleHeap : public SuperHeap {
  constexpr static auto sampling_window_envname =
      "SCALENE_ALLOCATION_SAMPLING_WINDOW";

 public:
  enum { Alignment = SuperHeap::Alignment };
  enum AllocSignal { MallocSignal = SIGXCPU, FreeSignal = SIGXFSZ };
  static constexpr uint64_t NEWLINE =
      98821;  // Sentinel value denoting a new line has executed

  SampleHeap()
      : _lastMallocTrigger(nullptr),
        _freedLastMallocTrigger(false),
        _allocationSampler(getenv(sampling_window_envname)
                               ? atol(getenv(sampling_window_envname))
                               : DefaultAllocationSamplingRateBytes) {
    getSampleFile();  // invoked here so the file gets initialized before python
                      // attempts to read from it

    get_signal_init_lock().lock();
    auto old_malloc = signal(MallocSignal, SIG_IGN);
    if (old_malloc != SIG_DFL) {
      signal(MallocSignal, old_malloc);
    }
    auto old_free = signal(FreeSignal, SIG_IGN);
    if (old_free != SIG_DFL) {
      signal(FreeSignal, old_free);
    }
    get_signal_init_lock().unlock();
  }

  ATTRIBUTE_ALWAYS_INLINE inline void* malloc(size_t sz) {
    MallocRecursionGuard g;
    auto ptr = SuperHeap::malloc(sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    if (pythonDetected() && !g.wasInMalloc()) {
      // All standard Python allocations pass through
      // MakeLocalAllocator in libscalene.cpp . 
      // We don't want to double-count these allocations--
      // if we're in here and g.wasInMalloc is true, then 
      // we passed through MakeLocalAllocator and
      // this allocation has already been counted
      //
      // We only want to count allocations here
      // if `malloc` itself was called by client code.
      auto realSize = SuperHeap::getSize(ptr);
      if (realSize > 0) {
        if (sz == NEWLINE + sizeof(ScaleneHeader)) {
          // FIXME
          //
          // If we ourselves are allocating a NEWLINE, we're doing
          // it through the Python allocator, so if it's an actual newline
          // I don't think we should ever get here. I think our original intention
          // is that we shouldn't count NEWLINE records that we already counted,
          // but I think if we get to this line here, we didn't actually create a NEWLINE
          // and should count it. 
          return ptr;
        }
        register_malloc(realSize, ptr, false);  // false -> invoked from C/C++
      }
    }
    return ptr;
  }
  ATTRIBUTE_ALWAYS_INLINE inline void* realloc(void* ptr, size_t sz) {
    MallocRecursionGuard g;
    if (!ptr) {
      ptr = SuperHeap::malloc(sz);
      return ptr;
    }
    if (sz == 0) {
      SuperHeap::free(ptr);
#if defined(__APPLE__)
      // 0 size = free. We return a small object.  This behavior is
      // apparently required under Mac OS X and optional under POSIX.
      return SuperHeap::malloc(1);
#else
      // For POSIX, don't return anything.
      return nullptr;
#endif
    }
    size_t objSize = SuperHeap::getSize(ptr);

    void* buf = SuperHeap::malloc(sz);
    size_t buf_size = buf ? SuperHeap::getSize(buf) : 0;
    if (buf) {
      if (objSize == buf_size) {
        // The objects are the same actual size.
        // Free the new object and return the original.
        SuperHeap::free(buf);
        return ptr;
      }
      // Copy the contents of the original object
      // up to the size of the new block.
      size_t minSize = (objSize < sz) ? objSize : sz;
      memcpy(buf, ptr, minSize);
    }

    // Free the old block.
    SuperHeap::free(ptr);
    if (buf) {
      if (sz < buf_size) {
        register_malloc(buf_size - sz, buf,
                        false);  // false -> invoked from C/C++
      } else if (sz > buf_size) {
        register_free(sz - buf_size, ptr);
      }
    }
    // Return a pointer to the new one.
    return buf;
  }
  inline void register_malloc(size_t realSize, void* ptr,
                              bool inPythonAllocator = true) {
    if (p_scalene_done) return;
    assert(realSize);
    // If this is the special NEWLINE value, trigger an update.
    if (unlikely(realSize == NEWLINE)) {
      std::string filename;
      // Originally, we had the following check around this line:
      //
      // ```
      // if (where != nullptr && where(filename, lineno, bytei))
      // ```
      // 
      // This was to prevent a NEWLINE record from being accidentally triggered by
      // non-Scalene code.
      //
      // However, by definition, we trigger a NEWLINE _after_ the line has
      // been executed, specifically on a `PyTrace_Line` event.
      //
      // If the absolute last line of a program makes an allocation, 
      // the next PyTrace_Line will occur inside `scalene_profiler.py` and not any client
      // code, since the line after the last line of the program is when Scalene starts its
      // teardown. 
      // 
      // In this case.  the `whereInPython` function will return 0, since whereInPython checks
      // if the current frame is in client code and the Scalene profiler teardown code is by definition 
      // not. 
      //
      // This risks letting allocations of length NEWLINE_TRIGGER_LENGTH that are not true NEWLINEs
      // create a NEWLINE record, but we view this as incredibly improbable. 
      writeCount(MallocSignal, realSize, ptr, filename, -1, -1);
      mallocTriggered()++;
      return;
    }
    size_t sampleMallocSize;
    auto sampleMalloc =
        _allocationSampler.increment(realSize, ptr, sampleMallocSize);
    if (inPythonAllocator) {
      _pythonCount += realSize;
    } else {
      _cCount += realSize;
    }
    if (unlikely(sampleMalloc)) {
      process_malloc(sampleMallocSize, ptr);
    }
  }

 private:
  void process_malloc(size_t sampleMalloc, void* ptr) {
    std::string filename;
    int lineno;
    int bytei;

    decltype(whereInPython)* where = p_whereInPython;
    if (where != nullptr && where(filename, lineno, bytei)) {
      writeCount(MallocSignal, sampleMalloc, ptr, filename, lineno, bytei);
#if !SCALENE_DISABLE_SIGNALS
      raise(MallocSignal);
#endif
      _lastMallocTrigger = ptr;
      _freedLastMallocTrigger = false;
      _pythonCount = 0;
      _cCount = 0;
      mallocTriggered()++;
    }
  }

 public:
  ATTRIBUTE_ALWAYS_INLINE inline void free(void* ptr) {
    MallocRecursionGuard g;
    if (unlikely(ptr == nullptr)) {
      return;
    }
    auto realSize = SuperHeap::getSize(ptr);
    SuperHeap::free(ptr);
    if (pythonDetected() && !g.wasInMalloc()) {
      register_free(realSize, ptr);
    }
  }

  inline void register_free(size_t realSize, void* ptr) {
    if (p_scalene_done) return;
    size_t sampleFreeSize;
    auto sampleFree =
        _allocationSampler.decrement(realSize, ptr, sampleFreeSize);

    if (unlikely(ptr && (ptr == _lastMallocTrigger))) {
      _freedLastMallocTrigger = true;
    }
    if (unlikely(sampleFree)) {
      process_free(sampleFreeSize);
    }
  }

 private:
  void process_free(size_t sampleFree) {
    std::string filename;
    int lineno = 1;
    int bytei = 0;

#if 1
    decltype(whereInPython)* where = p_whereInPython;
    if (where != nullptr && where(filename, lineno, bytei)) {
      ;
    }
#endif

    writeCount(FreeSignal, sampleFree, nullptr, filename, lineno, bytei);
#if !SCALENE_DISABLE_SIGNALS
    raise(FreeSignal);
#endif
    freeTriggered()++;
  }

 public:
  void* memalign(size_t alignment, size_t sz) {
    MallocRecursionGuard g;
    auto ptr = SuperHeap::memalign(alignment, sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    if (pythonDetected() && !g.wasInMalloc()) {
      auto realSize = SuperHeap::getSize(ptr);
      assert(realSize >= sz);
      // EDB 4 June 2023, disabled below, possibly spurious assertion
      // assert((sz < 16) || (realSize <= 2 * sz));
      register_malloc(realSize, ptr, false);  // false -> invoked from C/C++
    }
    return ptr;
  }

 private:
  // Prevent copying and assignment.
  SampleHeap(const SampleHeap&) = delete;
  SampleHeap& operator=(const SampleHeap&) = delete;

  static auto& mallocTriggered() {
    static std::atomic<uint64_t> _mallocTriggered{0};
    return _mallocTriggered;
  }
  static auto& freeTriggered() {
    static std::atomic<uint64_t> _freeTriggered{0};
    return _freeTriggered;
  }

  counterType _pythonCount{0};
  counterType _cCount{0};

  void* _lastMallocTrigger;
  bool _freedLastMallocTrigger;
#if 0
  typedef PoissonSampler Sampler;
#warning "Experimental use only: Poisson sampler"
#else
  typedef ThresholdSampler Sampler;
#endif

  Sampler _allocationSampler;

  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;

  void writeCount(AllocSignal sig, uint64_t count, void* ptr,
                  const std::string& filename, int lineno, int bytei) {
    char buf[SampleFile::MAX_BUFSIZE];
    if (_pythonCount == 0) {
      _pythonCount = 1;  // prevent 0/0
    }
    // Get the thread ID, which must match the logic used by Python.
    uint64_t thread_id;
#if defined(__APPLE__) || defined(BSD)
    // Use the OS X / BSD thread identifier function to get "actual" thread ID.
    pthread_threadid_np(pthread_self(), &thread_id);
#elif defined(__linux__)
    // On Linux, use gettid().
    thread_id = (uint64_t) gettid();
#else
    // On other systems, cast pthread_self and hope for the best.
    thread_id = (uint64_t) pthread_self();
#endif
   
    snprintf_(
        buf, sizeof(buf),
#if defined(__APPLE__)
        "%c,%llu,%llu,%f,%d,%p,%s,%d,%d,%lu\n\n",
#else
        "%c,%lu,%lu,%f,%d,%p,%s,%d,%d,%lu\n\n",
#endif
        ((sig == MallocSignal) ? 'M' : ((_freedLastMallocTrigger) ? 'f' : 'F')),
        mallocTriggered() + freeTriggered(), count,
        (float)_pythonCount / (_pythonCount + _cCount), getpid(),
        _freedLastMallocTrigger ? _lastMallocTrigger : ptr, filename.c_str(),
        lineno,
	bytei,
        thread_id);
    // Ensure we don't report last-malloc-freed multiple times.
    _freedLastMallocTrigger = false;
    getSampleFile().writeToFile(buf);
  }

  static HL::PosixLock& get_signal_init_lock() {
    static HL::PosixLock signal_init_lock;
    return signal_init_lock;
  }
};

#endif
