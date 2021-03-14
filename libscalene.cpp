#define SCALENE_DISABLE_SIGNALS 0  // for debugging only

#include <execinfo.h>
#include <heaplayers.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "common.hpp"
#include "memcpysampler.hpp"
#include "sampleheap.hpp"
#include "staticbufferheap.hpp"
#include "stprintf.h"
#include "tprintf.h"

#if defined(__APPLE__)
#include "macinterpose.h"
#endif

const uint64_t MallocSamplingRate = 1048576ULL;
const uint64_t MemcpySamplingRate = MallocSamplingRate * 2ULL;

#include "sysmallocheap.hpp"

class CustomHeapType : public HL::ThreadSpecificHeap<SampleHeap<MallocSamplingRate, SysMallocHeap>> {
 public:
  void lock() {}
  void unlock() {}
};

// This is a hack to have a long-living buffer
// to put init filename in

HL::PosixLock SampleFile::lock;

inline CustomHeapType &getTheCustomHeap() {
  static CustomHeapType thang;
  return thang;
}

auto &getSampler() {
  static MemcpySampler<MemcpySamplingRate> msamp;
  return msamp;
}

#if defined(__APPLE__)
#define LOCAL_PREFIX(x) xx##x
#else
#define LOCAL_PREFIX(x) x
#endif

extern "C" ATTRIBUTE_EXPORT void *LOCAL_PREFIX(memcpy)(void *dst,
                                                       const void *src,
                                                       size_t n) {
  auto result = getSampler().memcpy(dst, src, n);
  return result;
}

extern "C" ATTRIBUTE_EXPORT void *LOCAL_PREFIX(memmove)(void *dst,
                                                        const void *src,
                                                        size_t n) {
  auto result = getSampler().memmove(dst, src, n);
  return result;
}

extern "C" ATTRIBUTE_EXPORT char *LOCAL_PREFIX(strcpy)(char *dst,
                                                       const char *src) {
  auto result = getSampler().strcpy(dst, src);
  return result;
}

// Calling the custom heap's constructor or malloc may itself lead to malloc calls;
// to avoid an infinite recursion, we satisfy these from a static heap
typedef StaticBufferHeap<16 * 1048576> StaticHeapType;

inline StaticHeapType& getTheStaticHeap() {
  static StaticHeapType theStaticHeap;
  return theStaticHeap;
}

class MutexGuard {
  pthread_mutex_t& _m;
 public:
  MutexGuard(pthread_mutex_t& m) : _m(m) {
    if (pthread_mutex_lock(&_m) != 0) {
      abort();
    }
  }
  ~MutexGuard() {
    if (pthread_mutex_unlock(&_m) != 0) {
      abort();
    }
  }
};

#if !defined(PTHREAD_RECURSIVE_MUTEX_INITIALIZER)
  #define PTHREAD_RECURSIVE_MUTEX_INITIALIZER PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP
#endif

// In order to service ::malloc through a custom heap, the custom heap's constructor
// and its malloc method need to run; if either one of these, directly or indirectly,
// need to call ::malloc, that would lead to an infinite recursion.  To avoid this, we
// detect such recursive ::malloc calls using a thread-local boolean variable and service
// them from a statically allocated heap.
// 
// The thread-local variable's and the static heap's initialization must be done carefully
// so as not to require ::malloc when no heap is available to service it from. To further
// complicate things, ::malloc is/can be invoked early during executable startup, before
// C++ constructors for global objects.  On MacOS, this seems to happen before thread
// initialization: attempts to use thread_local or __thread lead to an abort() in _tlv_bootstrap.
//
// In the code below, we prefer pthread and __atomic calls to std::mutex, std::atomic, etc.,
// to minimize initialization and memory allocation requirements (potential and actual).
// If malloc and the C++ constructor is all we need, we can use static initializers within
// functions, such as in getTheStaticHeap().
static pthread_key_t inMallocKey;

inline bool isInMalloc() {
  // modified double-checked locking pattern (https://en.wikipedia.org/wiki/Double-checked_locking)
  static enum {NEEDS_KEY=0, CREATING_KEY=1, DONE=2} inMallocKeyState{NEEDS_KEY};
  static pthread_mutex_t m = PTHREAD_RECURSIVE_MUTEX_INITIALIZER;

  auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_ACQUIRE);
  if (state != DONE) {
    MutexGuard g(m);

    state = __atomic_load_n(&inMallocKeyState, __ATOMIC_RELAXED);
    if (unlikely(state == CREATING_KEY)) {
      return true;
    }
    else if (unlikely(state == NEEDS_KEY)) {
      __atomic_store_n(&inMallocKeyState, CREATING_KEY, __ATOMIC_RELAXED);
      if (pthread_key_create(&inMallocKey, 0) != 0) { // may call malloc/calloc/...
        abort();
      }
      __atomic_store_n(&inMallocKeyState, DONE, __ATOMIC_RELEASE);
    }
  }

  return pthread_getspecific(inMallocKey) != 0;
}

inline void setInMalloc(bool state) {
  pthread_setspecific(inMallocKey, state ? (void*)1 : 0);
}

extern "C" ATTRIBUTE_EXPORT void *xxmalloc(size_t sz) {
  if (unlikely(isInMalloc())) {
    return getTheStaticHeap().malloc(sz);
  }

  setInMalloc(true);
  void* ptr = getTheCustomHeap().malloc(sz);
  setInMalloc(false);
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT void xxfree(void *ptr) {
  if (likely(!getTheStaticHeap().isValid(ptr))) {
    getTheCustomHeap().free(ptr);
  }
}

extern "C" ATTRIBUTE_EXPORT void xxfree_sized(void *ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  xxfree(ptr);
}

extern "C" ATTRIBUTE_EXPORT void *xxmemalign(size_t alignment, size_t sz) {
  if (unlikely(isInMalloc())) {
    return getTheStaticHeap().malloc(sz); // FIXME 'alignment' ignored
  }

  setInMalloc(true);
  void* ptr = getTheCustomHeap().memalign(alignment, sz);
  setInMalloc(false);
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void *ptr) {
  if (unlikely(getTheStaticHeap().isValid(ptr))) {
    return getTheStaticHeap().getSize(ptr);
  }

  return getTheCustomHeap().getSize(ptr);  // TODO FIXME adjust for ptr offset?
}

extern "C" ATTRIBUTE_EXPORT void xxmalloc_lock() {
  getTheCustomHeap().lock();
}

extern "C" ATTRIBUTE_EXPORT void xxmalloc_unlock() {
  getTheCustomHeap().unlock();
}

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif
