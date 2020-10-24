#include <heaplayers.h>

#include <stdio.h>
#include <execinfo.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>

#include "stprintf.h"
#include "tprintf.h"
#include "common.hpp"

#include "sampleheap.hpp"
#include "memcpysampler.hpp"
#include "fastmemcpy.hpp"

#if defined(__APPLE__)
#include "macinterpose.h"
#include "tprintf.h"
#endif

// We use prime numbers here (near 1MB, for example) to reduce the risk
// of stride behavior interfering with sampling.

const auto MallocSamplingRate = 1048549UL;
const auto MemcpySamplingRate = 2097131UL; // next prime after MallocSamplingRate * 2 + 1;
// TBD: use sampler logic (with random sampling) to obviate the need for primes
// already doing this for malloc-sampling.

#include "nextheap.hpp"

//class CustomHeapType : public NextHeap {
//class CustomHeapType : public HL::ThreadSpecificHeap<NextHeap> {
class CustomHeapType : public HL::ThreadSpecificHeap<SampleHeap<MallocSamplingRate, NextHeap>> {
public:
  void lock() {}
  void unlock() {}
};

//typedef NextHeap CustomHeapType;

class InitializeMe {
public:
  InitializeMe()
  {
#if 1
    // invoke backtrace so it resolves symbols now
#if 0 // defined(__linux__)
    volatile void * dl = dlopen("libgcc_s.so.1", RTLD_NOW | RTLD_GLOBAL);
#endif
    void * callstack[4];
    auto frames = backtrace(callstack, 4);
#endif
    //    isInitialized = true;
  }
};

static volatile InitializeMe initme;

static CustomHeapType thang;

#define getTheCustomHeap() thang

#if 0
CustomHeapType& getTheCustomHeap() {
  static CustomHeapType thang;
  return thang;
}
#endif


auto& getSampler() {
  static MemcpySampler<MemcpySamplingRate> msamp;
  return msamp;
}

#if defined(__APPLE__)
#define LOCAL_PREFIX(x) xx##x
#else
#define LOCAL_PREFIX(x) x
#endif

extern "C" ATTRIBUTE_EXPORT void * LOCAL_PREFIX(memcpy)(void * dst, const void * src, size_t n) {
  // tprintf::tprintf("memcpy @ @ (@)\n", dst, src, n);
  auto result = getSampler().memcpy(dst, src, n);
  return result;
}

extern "C" ATTRIBUTE_EXPORT void * LOCAL_PREFIX(memmove)(void * dst, const void * src, size_t n) {
  auto result = getSampler().memmove(dst, src, n);
  return result;
}

extern "C" ATTRIBUTE_EXPORT char * LOCAL_PREFIX(strcpy)(char * dst, const char * src) {
  // tprintf::tprintf("strcpy @ @ (@)\n", dst, src);
  auto result = getSampler().strcpy(dst, src);
  return result;
}

extern "C" ATTRIBUTE_EXPORT void * xxmalloc(size_t sz) {
  void * ptr = nullptr;
  ptr = getTheCustomHeap().malloc(sz);
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT void xxfree(void * ptr) {
  getTheCustomHeap().free(ptr);
}

extern "C" ATTRIBUTE_EXPORT void xxfree_sized(void * ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  getTheCustomHeap().free(ptr);
}

extern "C" ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void * ptr) {
  return getTheCustomHeap().getSize(ptr); // TODO FIXME adjust for ptr offset?
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
