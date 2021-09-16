#pragma once

#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <assert.h>
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

// We're unable to use the limited API because, for example,
// there doesn't seem to be a function returning co_filename
//#define Py_LIMITED_API 0x03070000

#include <Python.h>
#include <frameobject.h>

#include "common.hpp"
#include "mallocrecursionguard.hpp"
#include "open_addr_hashtable.hpp"
#include "printf.h"
#include "samplefile.hpp"
#include "sampler.hpp"
#include "py_env.hpp"
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

template <uint64_t MallocSamplingRateBytes,
	  uint64_t FreeSamplingRateBytes,
	  class SuperHeap>
class SampleHeap : public SuperHeap {
  static constexpr int MAX_FILE_SIZE = 4096 * 65536;
  
 public:
  enum { Alignment = SuperHeap::Alignment };
  enum AllocSignal { MallocSignal = SIGXCPU, FreeSignal = SIGXFSZ };

  SampleHeap()
      : _lastMallocTrigger(nullptr),
        _freedLastMallocTrigger(false)
  {
    getSampleFile(); // invoked here so the file gets initialized before python attempts to read from it

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
    MallocRecursionGuard g;
    auto ptr = SuperHeap::malloc(sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    if (!g.wasInMalloc()) {
      auto realSize = SuperHeap::getSize(ptr);
      if (realSize > 0) {
	register_malloc(realSize, ptr, false); // false -> invoked from C/C++
      }
    }
    return ptr;
  }


  inline void register_malloc(size_t realSize, void * ptr, bool inPythonAllocator = true) {
    assert(realSize);
    auto sampleMalloc = _mallocSampler.sample(realSize);
    if (inPythonAllocator) {
      _pythonCount += realSize;
    } else {
      _cCount += realSize;
    }
    if (unlikely(sampleMalloc)) {
      std::string filename;
      int lineno;
      int bytei;
      int r = getPythonInfo(filename, lineno, bytei);
      if (r) {
        // printf_("MALLOC HANDLED (SAMPLEHEAP): %p -> %lu (%s, %d)\n", ptr, sampleMalloc, filename.c_str(), lineno);
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
  }
  
  ATTRIBUTE_ALWAYS_INLINE inline void free(void *ptr) {
    MallocRecursionGuard g;

    if (unlikely(ptr == nullptr)) {
      return;
    }
    if (!g.wasInMalloc()) {
      auto realSize = SuperHeap::getSize(ptr);
      register_free(realSize, ptr);
    }
    SuperHeap::free(ptr);
  }

  inline void register_free(size_t realSize, void * ptr) {
#if 0
    // Experiment: frees 'unsample' the allocation counter. This
    // approach means ignoring allocation swings less than the
    // sampling period (on average).
    _mallocSampler.unsample(realSize);
#endif
    auto sampleFree = _freeSampler.sample(realSize);
    if (unlikely(ptr && (ptr == _lastMallocTrigger))) {
      _freedLastMallocTrigger = true;
    }
    if (unlikely(sampleFree)) {
      std::string filename;
      int lineno;
      int bytei;

      int r = getPythonInfo(filename, lineno, bytei);
      if (r) {
        // printf_("FREE HANDLED (SAMPLEHEAP): %p -> (%s, %d)\n", ptr, filename.c_str(), lineno);
        writeCount(FreeSignal, sampleFree, nullptr, filename, lineno, bytei);
#if !SCALENE_DISABLE_SIGNALS
        raise(MallocSignal); // was FreeSignal
#endif
        freeTriggered()++;
      }
    }
  }

  void *memalign(size_t alignment, size_t sz) {
    MallocRecursionGuard g;
    auto ptr = SuperHeap::memalign(alignment, sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    if (!g.wasInMalloc()) {
      auto realSize = SuperHeap::getSize(ptr);
      assert(realSize >= sz);
      assert((sz < 16) || (realSize <= 2 * sz));
      register_malloc(realSize, ptr);
    }
    return ptr;
  }

 private:

  // An RAII class to simplify acquiring and releasing the GIL.
  class GIL {
  public:
    GIL()
    {
      _gstate = PyGILState_Ensure();
    }
    ~GIL() {
      PyGILState_Release(_gstate);
    }
  private:
    PyGILState_STATE _gstate;
  };


  // Implements a mini smart pointer to PyObject.
  // Manages a "strong" reference to the object... to use with a weak reference, Py_IncRef it first.
  // Unfortunately, not all PyObject subclasses (e.g., PyFrameObject) are declared as such,
  // so we need to make this a template and cast.
  template<class O = PyObject>
  class PyPtr {
  public:
    PyPtr(O* o) : _obj(o) {}

    O* operator->() {
        return _obj;
    }

    operator O* () {
        return _obj;
    }

    PyPtr& operator=(O* o) {
      Py_DecRef((PyObject*)_obj);
      _obj = o;
      return *this;
    }

    PyPtr& operator=(PyPtr& ptr) {
      Py_IncRef((PyObject*)ptr._obj);
      *this = ptr._obj;
      return *this;
    }

    ~PyPtr() {
      Py_DecRef((PyObject*)_obj);
    }

  private:
    O* _obj;
  };

  int getPythonInfo(std::string& filename, int& lineno, int& bytei) {
    if (!Py_IsInitialized()) {
      return 0;
    }
    // This function walks the Python stack until it finds a frame
    // corresponding to a file we are actually profiling. On success,
    // it updates filename, lineno, and byte code index appropriately,
    // and returns 1.  If the stack walk encounters no such file, it
    // sets the filename to the pseudo-filename "<BOGUS>" for special
    // treatment within Scalene, and returns 0.
    filename = "<BOGUS>";
    lineno = 1;
    bytei = 0;
    GIL gil; 

    if (PyGILState_GetThisThreadState() == 0) {
      return 0;
    }

    for (auto frame = PyEval_GetFrame(); frame != nullptr; frame = frame->f_back) {
      auto fname = frame->f_code->co_filename;
      PyPtr<> encoded = PyUnicode_AsASCIIString(fname);
      if (!encoded) {
        return 0;
      }

      auto filenameStr = PyBytes_AsString(encoded);
      if (strlen(filenameStr) == 0) {
        continue;
      }

      if (!strstr(filenameStr, "<")
          && !strstr(filenameStr, "/python")
          && !strstr(filenameStr, "scalene/scalene")) {
            if (py_string_ptr_list.should_trace(filenameStr) == 1) {
#if defined(PyPy_FatalError)
              // If this macro is defined, we are compiling PyPy, which
              // AFAICT does not have any way to access bytecode index, so
              // we punt and set it to 0.
              bytei = 0;
  #else
              bytei = frame->f_lasti;
  #endif
              lineno = PyCode_Addr2Line(frame->f_code, bytei);

              filename = filenameStr;
              // printf_("FOUND IT: %s %d\n", filenameStr, lineno);
              return 1;
            }
      }
    } 
    return 0;
  }
  
  // Prevent copying and assignment.
  SampleHeap(const SampleHeap &) = delete;
  SampleHeap &operator=(const SampleHeap &) = delete;


  Sampler<MallocSamplingRateBytes> _mallocSampler;
  Sampler<FreeSamplingRateBytes> _freeSampler;
  
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

  void *_lastMallocTrigger;
  bool _freedLastMallocTrigger;

  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;

  void writeCount(AllocSignal sig, uint64_t count, void *ptr, const std::string& filename, int lineno, int bytei) {
    char buf[SampleFile::MAX_BUFSIZE];
    if (_pythonCount == 0) {
      _pythonCount = 1;  // prevent 0/0
    }
    snprintf_(
        buf, SampleFile::MAX_BUFSIZE,
#if defined(__APPLE__)
        "%c,%llu,%llu,%f,%d,%p,%s,%d,%d\n\n",
#else
        "%c,%lu,%lu,%f,%d,%p,%s,%d,%d\n\n",
#endif
        ((sig == MallocSignal) ? 'M' : ((_freedLastMallocTrigger) ? 'f' : 'F')),
        mallocTriggered() + freeTriggered(), count,
        (float)_pythonCount / (_pythonCount + _cCount), getpid(),
        _freedLastMallocTrigger ? _lastMallocTrigger : ptr,
	filename.c_str(),
	lineno,
	bytei);
    // Ensure we don't report last-malloc-freed multiple times.
    _freedLastMallocTrigger = false;
    getSampleFile().writeToFile(buf);
  }

  static HL::PosixLock &get_signal_init_lock() {
    static HL::PosixLock signal_init_lock;
    return signal_init_lock;
  }
};

#endif
