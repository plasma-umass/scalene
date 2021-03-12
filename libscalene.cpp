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

// XXX use ': char'? implicitly atomic?
static enum {NEEDS_INIT=0, INITIALIZING=1, DONE=2} inMallocKeyState{NEEDS_INIT};
static pthread_key_t inMallocKey;

class MutexGuard {
  pthread_mutex_t& _m;
 public:
  MutexGuard(pthread_mutex_t& m) : _m(m) {
    pthread_mutex_lock(&_m); // XXX check return
  }
  ~MutexGuard() {
    pthread_mutex_unlock(&_m); // XXX check return
  }
};

#if !defined(PTHREAD_RECURSIVE_MUTEX_INITIALIZER)
  #define PTHREAD_RECURSIVE_MUTEX_INITIALIZER PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP
#endif

inline bool isInMalloc() {
  auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_ACQUIRE); // XXX __ATOMIC_CONSUME?
  if (state != DONE) {
    static pthread_mutex_t m = PTHREAD_RECURSIVE_MUTEX_INITIALIZER;
    MutexGuard g(m);

    state = __atomic_load_n(&inMallocKeyState, __ATOMIC_RELAXED);
    if (unlikely(state == INITIALIZING)) {
      return true;
    }
    else if (unlikely(state == NEEDS_INIT)) {
      // 'initializing' in case pthread_key_create calls malloc/calloc/...
      __atomic_store_n(&inMallocKeyState, INITIALIZING, __ATOMIC_RELAXED);
      if (pthread_key_create(&inMallocKey, 0) != 0) {
        // XXX abort?
      }
      __atomic_store_n(&inMallocKeyState, DONE, __ATOMIC_RELEASE);
    }
  }

  return pthread_getspecific(inMallocKey) != 0;
}

inline void setInMalloc(bool state) {
  pthread_setspecific(inMallocKey, state ? (void*)1 : 0);
}

// malloc() et al may be (and generally speaking are) invoked before C++ invokes
// global/static objects' constructors.  We work around this by declaring them
// static within functions and returning references to the objects.

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
