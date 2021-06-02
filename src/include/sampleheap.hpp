#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <dlfcn.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/errno.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>  // for getpid()

#include <atomic>
#include <random>

#include "common.hpp"
#include "open_addr_hashtable.hpp"
#include "printf.h"
#include "samplefile.hpp"
#include "sampler.hpp"

#define USE_ATOMICS 0

#if USE_ATOMICS
typedef std::atomic<uint64_t> counterType;
#else
typedef uint64_t counterType;
#endif

template <uint64_t MallocSamplingRateBytes,
	  uint64_t FreeSamplingRateBytes,
	  class SuperHeap>
class SampleHeap : public SuperHeap {
  static constexpr int MAX_FILE_SIZE = 4096 * 65536;

 public:
  enum { Alignment = SuperHeap::Alignment };
  enum AllocSignal { MallocSignal = SIGXCPU, FreeSignal = SIGXFSZ };
  enum {
    CallStackSamplingRate = MallocSamplingRateBytes * 10
  };  // 10 here just to reduce overhead

  SampleHeap()
      : _samplefile((char *)"/tmp/scalene-malloc-signal%d",
                    (char *)"/tmp/scalene-malloc-lock%d",
                    (char *)"/tmp/scalene-malloc-init%d"),
        _pid(getpid()),
        _lastMallocTrigger(nullptr),
        _freedLastMallocTrigger(false) {
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
    int pid = getpid();
  }

  ATTRIBUTE_ALWAYS_INLINE inline void *malloc(size_t sz) {
    auto ptr = SuperHeap::malloc(sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    auto realSize = SuperHeap::getSize(ptr);
    assert(realSize >= sz);
    auto sampleMalloc = _mallocSampler.sample(realSize);
    auto sampleCallStack = _callStackSampler.sample(realSize);
    if (unlikely(sampleCallStack)) {
      recordCallStack(realSize);
    }
    if (unlikely(sampleMalloc)) {
      handleMalloc(sampleMalloc, ptr);
    }
    return ptr;
  }

  ATTRIBUTE_ALWAYS_INLINE inline void free(void *ptr) {
    if (unlikely(ptr == nullptr)) {
      return;
    }
    auto realSize = SuperHeap::getSize(ptr);
    auto sampleFree = _freeSampler.sample(realSize);
    if (unlikely(ptr == _lastMallocTrigger)) {
      _freedLastMallocTrigger = true;
    }
    if (unlikely(sampleFree)) {
      handleFree(sampleFree);
    }
    SuperHeap::free(ptr);
  }

  void *memalign(size_t alignment, size_t sz) {
    auto ptr = SuperHeap::memalign(alignment, sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    auto realSize = SuperHeap::getSize(ptr);
    assert(realSize >= sz);
    assert((sz < 16) || (realSize <= 2 * sz));
    auto sampleMalloc = _mallocSampler.sample(realSize);
    auto sampleCallStack = _callStackSampler.sample(realSize);
    if (unlikely(sampleCallStack)) {
      recordCallStack(realSize);
    }
    if (unlikely(sampleMalloc)) {
      handleMalloc(sampleMalloc, ptr);
    }
    return ptr;
  }

 private:
  // Prevent copying and assignment.
  SampleHeap(const SampleHeap &) = delete;
  SampleHeap &operator=(const SampleHeap &) = delete;

  void handleMalloc(size_t sampleMalloc, void *triggeringMallocPtr) {
    writeCount(MallocSignal, sampleMalloc, triggeringMallocPtr);

#if !SCALENE_DISABLE_SIGNALS
    raise(MallocSignal);
#endif
    _lastMallocTrigger = triggeringMallocPtr;
    _freedLastMallocTrigger = false;
    _pythonCount = 0;
    _cCount = 0;
    mallocTriggered()++;
  }

  void handleFree(size_t sampleFree) {
    writeCount(FreeSignal, sampleFree, nullptr);
#if !SCALENE_DISABLE_SIGNALS
    raise(MallocSignal); // was FreeSignal
#endif
    freeTriggered()++;
  }

  Sampler<MallocSamplingRateBytes> _mallocSampler;
  Sampler<FreeSamplingRateBytes> _freeSampler;
  Sampler<CallStackSamplingRate> _callStackSampler;
  
  static auto& mallocTriggered() {
    static std::atomic<uint64_t> _mallocTriggered {0};
    return _mallocTriggered;
  }
  static auto& freeTriggered() {
    static std::atomic<uint64_t> _freeTriggered {0};
    return _freeTriggered;
  }
  
  counterType _pythonCount {0};
  counterType _cCount {0};

  open_addr_hashtable<65536>
      _table;  // Maps call stack entries to function names.
  SampleFile _samplefile;
  pid_t _pid;
  void recordCallStack(size_t sz) {
    // Walk the stack to see if this memory was allocated by Python
    // through its object allocation APIs.
    const auto MAX_FRAMES_TO_CHECK =
        4;  // enough to skip past the replacement_malloc
    void *callstack[MAX_FRAMES_TO_CHECK];
    auto frames = backtrace(callstack, MAX_FRAMES_TO_CHECK);
    char *fn_name;
    for (auto i = 0; i < frames; i++) {
      fn_name = nullptr;

#define USE_HASHTABLE 1
#if !USE_HASHTABLE
      auto v = nullptr;
#else
      auto v = _table.get(callstack[i]);
#endif
      if (v == nullptr) {
        // Not found. Add to table.
        Dl_info info;
        int r = dladdr(callstack[i], &info);
        if (r) {
#if !USE_HASHTABLE
#else
          _table.put(callstack[i], (void *)info.dli_sname);
#endif
          fn_name = (char *)info.dli_sname;
        } else {
          continue;
        }
      } else {
        // Found it.
        fn_name = (char *)v;
      }
      if (!fn_name) {
        continue;
      }
      if (strlen(fn_name) < 9) {  // length of PySet_New
        continue;
      }
      // Starts with Py, assume it's Python calling.
      if (strstr(fn_name, "Py") == &fn_name[0]) {
        if (strstr(fn_name, "PyArray_")) {
          // Make sure we're not in NumPy, which irritatingly exports some
          // functions starting with "Py"...
          goto C_CODE;
        }
#if 0
	if (strstr(fn_name, "PyEval") || strstr(fn_name, "PyCompile") || strstr(fn_name, "PyImport")) {
	  // Ignore allocations due to interpreter internal operations, for now.
	  goto C_CODE;
	}
#endif
        _pythonCount += sz;
        return;
      }
      if (strstr(fn_name, "_Py") == 0) {
        continue;
      }
      if (strstr(fn_name, "_PyCFunction")) {
        goto C_CODE;
      }
#if 1
      _pythonCount += sz;
      return;
#else
      // TBD: realloc requires special handling.
      // * _PyObject_Realloc
      // * _PyMem_Realloc
      if (strstr(fn_name, "New")) {
        _pythonCount += sz;
        return;
      }
      if (strstr(fn_name, "_PyObject_")) {
        if ((strstr(fn_name, "GC_Alloc")) || (strstr(fn_name, "GC_New")) ||
            (strstr(fn_name, "GC_NewVar")) || (strstr(fn_name, "GC_Resize")) ||
            (strstr(fn_name, "Malloc")) || (strstr(fn_name, "Calloc"))) {
          _pythonCount += sz;
          return;
        }
      }
      if (strstr(fn_name, "_PyMem_")) {
        if ((strstr(fn_name, "Malloc")) || (strstr(fn_name, "Calloc")) ||
            (strstr(fn_name, "RawMalloc")) || (strstr(fn_name, "RawCalloc"))) {
          _pythonCount += sz;
          return;
        }
      }
#endif
    }

  C_CODE:
    _cCount += sz;
  }

  void *_lastMallocTrigger;
  bool _freedLastMallocTrigger;

  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;

  void writeCount(AllocSignal sig, uint64_t count, void *ptr) {
    char buf[SampleFile::MAX_BUFSIZE];
    if (_pythonCount == 0) {
      _pythonCount = 1;  // prevent 0/0
    }
    snprintf(
        buf, SampleFile::MAX_BUFSIZE,
#if defined(__APPLE__)
        "%c,%llu,%llu,%f,%d,%p\n\n",
#else
        "%c,%lu,%lu,%f,%d,%p\n\n",
#endif
        ((sig == MallocSignal) ? 'M' : ((_freedLastMallocTrigger) ? 'f' : 'F')),
        mallocTriggered() + freeTriggered(), count,
        (float)_pythonCount / (_pythonCount + _cCount), getpid(),
        _freedLastMallocTrigger ? _lastMallocTrigger : ptr);
    // Ensure we don't report last-malloc-freed multiple times.
    _freedLastMallocTrigger = false;
    _samplefile.writeToFile(buf, 1);
  }

  HL::PosixLock &get_signal_init_lock() {
    static HL::PosixLock signal_init_lock;
    return signal_init_lock;
  }
};

#endif
