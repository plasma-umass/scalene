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

// FIXME document
class StaticMutex {
  #if !defined(PTHREAD_RECURSIVE_MUTEX_INITIALIZER)
    #define PTHREAD_RECURSIVE_MUTEX_INITIALIZER PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP
  #endif

  pthread_mutex_t _m;

 public:
  StaticMutex() : _m(PTHREAD_RECURSIVE_MUTEX_INITIALIZER) {}

  class Guard {
    pthread_mutex_t& _m;

   public:
    Guard(StaticMutex& m) : _m(m._m) {
      if (pthread_mutex_lock(&_m) != 0) {
        abort();
      }
    }
    ~Guard() {
      if (pthread_mutex_unlock(&_m) != 0) {
        abort();
      }
    }
  };
};

/**
 * Interposes a custom heap ahead of the system heap, relying on Heap-Layers' wrappers.
 *
 * In order to service ::malloc through a custom heap, the custom heap's constructor
 * and its malloc method need to run; if either one of these, directly or indirectly,
 * need to call ::malloc, that would lead to an infinite recursion.  To avoid this, we
 * detect such recursive ::malloc calls using a thread-local boolean variable and service
 * them from a statically allocated heap.
 *
 * The thread-local variable's and the static heap's initialization must be done carefully
 * so as not to require ::malloc when no heap is available to service it from. To further
 * complicate things, ::malloc is/can be invoked early during executable startup, before
 * C++ constructors for global objects.  On MacOS, this seems to happen before thread
 * initialization: attempts to use thread_local or __thread lead to an abort() in _tlv_bootstrap.
 *
 * In the code below, we prefer pthread and __atomic calls to std::mutex, std::atomic, etc.,
 * to minimize initialization and memory allocation requirements (potential and actual).
 * If malloc and the C++ constructor is all we need, we can use static initializers within
 * functions, such as in getTheStaticHeap().
 */
#define INTERPOSE_HEAP(CustomHeap, staticSize) \
namespace __heap_interpose {\
  static pthread_key_t _inMallocKey;\
\
  inline bool isInMalloc() {\
    /* modified double-checked locking pattern (https://en.wikipedia.org/wiki/Double-checked_locking) */ \
    static enum {NEEDS_KEY=0, CREATING_KEY=1, DONE=2} inMallocKeyState{NEEDS_KEY};\
    static StaticMutex m;\
\
    auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_ACQUIRE);\
    if (state != DONE) {\
      StaticMutex::Guard g(m);\
\
      state = __atomic_load_n(&inMallocKeyState, __ATOMIC_RELAXED);\
      if (unlikely(state == CREATING_KEY)) {\
        return true;\
      }\
      else if (unlikely(state == NEEDS_KEY)) {\
        __atomic_store_n(&inMallocKeyState, CREATING_KEY, __ATOMIC_RELAXED);\
        if (pthread_key_create(&_inMallocKey, 0) != 0) { /* may call malloc/calloc/...*/\
          abort();\
        }\
        __atomic_store_n(&inMallocKeyState, DONE, __ATOMIC_RELEASE);\
      }\
    }\
\
    return pthread_getspecific(_inMallocKey) != 0;\
  }\
\
  inline static void setInMalloc(bool state) {\
    pthread_setspecific(_inMallocKey, state ? (void*)1 : 0);\
  }\
\
  inline static StaticBufferHeap<staticSize>& getTheStaticHeap() {\
    static StaticBufferHeap<staticSize> theStaticHeap;\
    return theStaticHeap;\
  }\
\
  inline static CustomHeap &getTheCustomHeap() {\
    static CustomHeap thang;\
    return thang;\
  }\
}\
\
extern "C" {\
  using namespace __heap_interpose;\
\
  void* xxmalloc(size_t sz) {\
    if (unlikely(isInMalloc())) {\
      return getTheStaticHeap().malloc(sz);\
    }\
\
    setInMalloc(true);\
    void* ptr = getTheCustomHeap().malloc(sz);\
    setInMalloc(false);\
    return ptr;\
  }\
\
  void *xxmemalign(size_t alignment, size_t sz) {\
    if (unlikely(isInMalloc())) {\
      return getTheStaticHeap().malloc(sz); /* FIXME 'alignment' ignored */\
    }\
\
    setInMalloc(true);\
    void* ptr = getTheCustomHeap().memalign(alignment, sz);\
    setInMalloc(false);\
    return ptr;\
  }\
\
  void xxfree(void* ptr) {\
    if (likely(!getTheStaticHeap().isValid(ptr))) {\
      getTheCustomHeap().free(ptr);\
    }\
  }\
\
  size_t xxmalloc_usable_size(void *ptr) {\
    if (unlikely(getTheStaticHeap().isValid(ptr))) {\
      return getTheStaticHeap().getSize(ptr);\
    }\
\
    return getTheCustomHeap().getSize(ptr);\
  }\
\
  void xxmalloc_lock() {\
    getTheCustomHeap().lock();\
  }\
\
  void xxmalloc_unlock() {\
    getTheCustomHeap().unlock();\
  }\
}

INTERPOSE_HEAP(CustomHeapType, 8 * 1024 * 1024);

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif
