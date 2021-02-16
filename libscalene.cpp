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
#include "tprintf.h"
#endif

const uint64_t MallocSamplingRate = 1048576ULL;
const uint64_t MemcpySamplingRate = MallocSamplingRate * 2ULL;

#include "nextheap.hpp"

class ParentHeap
    : public HL::ThreadSpecificHeap<SampleHeap<MallocSamplingRate, NextHeap>> {
};

static bool _initialized{false};

class CustomHeapType : public ParentHeap {
 public:
  CustomHeapType() { _initialized = true; }
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

CustomHeapType &getTheCustomHeap() {
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

StaticBufferHeap<16 * 1048576> buffer;

static bool _inMalloc = false;

extern "C" ATTRIBUTE_EXPORT void *xxmalloc(size_t sz) {
  if (_inMalloc) {
    buffer.malloc(sz);
  }
  void *ptr = nullptr;
  _inMalloc = true;
  ptr = getTheCustomHeap().malloc(sz);
  _inMalloc = false;
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT void xxfree(void *ptr) {
  if (!_initialized) {
    return;
  }
  if (buffer.isValid(ptr)) {
    return;
  }
  getTheCustomHeap().free(ptr);
}

extern "C" ATTRIBUTE_EXPORT void xxfree_sized(void *ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  getTheCustomHeap().free(ptr);
}

extern "C" ATTRIBUTE_EXPORT void *xxmemalign(size_t alignment, size_t sz) {
  if (_initialized) {
    return getTheCustomHeap().memalign(alignment, sz);
  } else {
    // FIXME
    return buffer.malloc(sz);
  }
}

extern "C" ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void *ptr) {
  if (buffer.isValid(ptr)) {
    return buffer.getSize(ptr);
  }
  return getTheCustomHeap().getSize(ptr);  // TODO FIXME adjust for ptr offset?
}

extern "C" ATTRIBUTE_EXPORT void xxmalloc_lock() { getTheCustomHeap().lock(); }

extern "C" ATTRIBUTE_EXPORT void xxmalloc_unlock() {
  getTheCustomHeap().unlock();
}

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif
