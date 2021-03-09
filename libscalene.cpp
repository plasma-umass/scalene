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

// typedef NextHeap CustomHeapType;

// This is a hack to have a long-living buffer
// to put init filename in

class InitializeMe {
 public:
  InitializeMe() {
#if 1
    // invoke backtrace so it resolves symbols now
#if 0  // defined(__linux__)
    volatile void * dl = dlopen("libgcc_s.so.1", RTLD_NOW | RTLD_GLOBAL);
#endif
    void *callstack[4];
    auto frames = backtrace(callstack, 4);
#endif
    //    isInitialized = true;
  }
};

static volatile InitializeMe initme;
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

inline bool& getInMallocFlag() {
  static thread_local bool inMalloc{false};
  return inMalloc;
}

// malloc() et al may be (and generally speaking are) invoked before C++ invokes
// global/static objects' constructors.  We work around this by working with "getter"
// functions, such getTheCustomHeap, getTheStaticHeap and getInMallocFlag.
// In getInMallocFlag's case, actually, the getter a bit of defensive programming because
// of its thread_local storage, as it should otherwise be ok to initialize it at compile 
// time as a static bool in global scope.

extern "C" ATTRIBUTE_EXPORT void *xxmalloc(size_t sz) {
  if (getInMallocFlag()) {
    return getTheStaticHeap().malloc(sz);
  }
  getInMallocFlag() = true;
  void* ptr = getTheCustomHeap().malloc(sz);
  getInMallocFlag() = false;
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT void xxfree(void *ptr) {
  if (!getTheStaticHeap().isValid(ptr)) {
    getTheCustomHeap().free(ptr);
  }
}

extern "C" ATTRIBUTE_EXPORT void xxfree_sized(void *ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  xxfree(ptr);
}

extern "C" ATTRIBUTE_EXPORT void *xxmemalign(size_t alignment, size_t sz) {
  if (getInMallocFlag()) {
    return getTheStaticHeap().malloc(sz); // FIXME 'alignment' ignored
  }

  getInMallocFlag() = true;
  void* ptr = getTheCustomHeap().memalign(alignment, sz);
  getInMallocFlag() = false;
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void *ptr) {
  if (getTheStaticHeap().isValid(ptr)) {
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
