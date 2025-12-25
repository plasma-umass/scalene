#pragma once

#ifndef SAMPLEHEAP_WIN_H
#define SAMPLEHEAP_WIN_H

#if defined(_WIN32)

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <atomic>
#include <random>
#include <string>
#include <cstdlib>
#include <cstdio>
#include <process.h>

#include "common_win.hpp"
#include "mallocrecursionguard_win.hpp"
#include "printf.h"
#include "pywhere.hpp"
#include "samplefile_win.hpp"
#include "scaleneheader.hpp"
#include "thresholdsampler.hpp"

// Windows doesn't have SIGXCPU/SIGXFSZ, so we use Windows Events instead
// The Python side will wait on these events

static SampleFile& getSampleFile() {
  static SampleFile mallocSampleFile("/tmp/scalene-malloc-signal%d",
                                     "/tmp/scalene-malloc-lock%d",
                                     "/tmp/scalene-malloc-init%d");
  return mallocSampleFile;
}

// Windows Event handles for signaling Python
static HANDLE& getMallocEvent() {
  static HANDLE hEvent = NULL;
  if (hEvent == NULL) {
    char eventName[256];
    snprintf_(eventName, sizeof(eventName), "Local\\scalene-malloc-event%d", _getpid());
    hEvent = CreateEventA(NULL, FALSE, FALSE, eventName);  // Auto-reset event
  }
  return hEvent;
}

static HANDLE& getFreeEvent() {
  static HANDLE hEvent = NULL;
  if (hEvent == NULL) {
    char eventName[256];
    snprintf_(eventName, sizeof(eventName), "Local\\scalene-free-event%d", _getpid());
    hEvent = CreateEventA(NULL, FALSE, FALSE, eventName);
  }
  return hEvent;
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
  // Using events instead of signals on Windows
  enum AllocEvent { MallocEvent = 0, FreeEvent = 1 };
  static constexpr uint64_t NEWLINE =
      98821;  // Sentinel value denoting a new line has executed

  SampleHeap()
      : _lastMallocTrigger(nullptr),
        _freedLastMallocTrigger(false),
        _allocationSampler(getenv(sampling_window_envname)
                               ? atol(getenv(sampling_window_envname))
                               : DefaultAllocationSamplingRateBytes) {
    getSampleFile();  // Initialize the file before Python reads from it

    // Initialize Windows events
    getMallocEvent();
    getFreeEvent();
  }

  ATTRIBUTE_ALWAYS_INLINE inline void* malloc(size_t sz) {
    MallocRecursionGuard g;
    auto ptr = SuperHeap::malloc(sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    if (pythonDetected() && !g.wasInMalloc()) {
      auto realSize = SuperHeap::getSize(ptr);
      if (realSize > 0) {
        if (sz == NEWLINE + sizeof(ScaleneHeader)) {
          return ptr;
        }
        register_malloc(realSize, ptr, false);
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
      // Windows: return small object (same as macOS behavior)
      return SuperHeap::malloc(1);
    }
    size_t objSize = SuperHeap::getSize(ptr);

    void* buf = SuperHeap::malloc(sz);
    size_t buf_size = buf ? SuperHeap::getSize(buf) : 0;
    if (buf) {
      if (objSize == buf_size) {
        SuperHeap::free(buf);
        return ptr;
      }
      size_t minSize = (objSize < sz) ? objSize : sz;
      memcpy(buf, ptr, minSize);
    }

    SuperHeap::free(ptr);
    if (buf) {
      if (sz < buf_size) {
        register_malloc(buf_size - sz, buf, false);
      } else if (sz > buf_size) {
        register_free(sz - buf_size, ptr);
      }
    }
    return buf;
  }

  inline void register_malloc(size_t realSize, void* ptr,
                              bool inPythonAllocator = true) {
    if (p_scalene_done) return;
    if (unlikely(realSize == NEWLINE)) {
      std::string filename;
      writeCount(MallocEvent, realSize, ptr, filename, -1, -1);
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
      writeCount(MallocEvent, sampleMalloc, ptr, filename, lineno, bytei);
      // Signal the event instead of raising a signal
      HANDLE hEvent = getMallocEvent();
      if (hEvent) {
        SetEvent(hEvent);
      }
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

    decltype(whereInPython)* where = p_whereInPython;
    if (where != nullptr && where(filename, lineno, bytei)) {
      ;
    }

    writeCount(FreeEvent, sampleFree, nullptr, filename, lineno, bytei);
    HANDLE hEvent = getFreeEvent();
    if (hEvent) {
      SetEvent(hEvent);
    }
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
      register_malloc(realSize, ptr, false);
    }
    return ptr;
  }

 private:
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

  typedef ThresholdSampler Sampler;
  Sampler _allocationSampler;

  void writeCount(AllocEvent evt, uint64_t count, void* ptr,
                  const std::string& filename, int lineno, int bytei) {
    char buf[SampleFile::MAX_BUFSIZE];
    if (_pythonCount == 0) {
      _pythonCount = 1;
    }
    snprintf_(
        buf, sizeof(buf),
        "%c,%llu,%llu,%f,%d,%p,%s,%d,%d\n\n",
        ((evt == MallocEvent) ? 'M' : ((_freedLastMallocTrigger) ? 'f' : 'F')),
        (unsigned long long)(mallocTriggered() + freeTriggered()),
        (unsigned long long)count,
        (float)_pythonCount / (_pythonCount + _cCount),
        _getpid(),
        _freedLastMallocTrigger ? _lastMallocTrigger : ptr,
        filename.c_str(),
        lineno, bytei);
    _freedLastMallocTrigger = false;
    getSampleFile().writeToFile(buf);
  }
};

#endif // _WIN32

#endif // SAMPLEHEAP_WIN_H
