#define SCALENE_DISABLE_SIGNALS 0  // for debugging only

#if !defined(_WIN32)
#include <execinfo.h>
#include <unistd.h>
#endif

#include <heaplayers.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>

#include <cstddef>

#if defined(__APPLE__)
#include "hoardtlab.h"  // must come before common.hpp
#endif

#include "common.hpp"
#include "heapredirect.h"
#include "memcpysampler.hpp"
#include "sampleheap.hpp"
#include "stprintf.h"
#include "tprintf.h"

#if defined(__APPLE__)
#include "macinterpose.h"
#endif

#if defined(__APPLE__)
// Using the system allocator rather than Python's would add too much overhead;
// we use Hoard instead to avoid that.

class ScaleneBaseHeap : public HL::ANSIWrapper<Hoard::TLABBase> {
  using super = HL::ANSIWrapper<Hoard::TLABBase>;

  static Hoard::HoardHeapType *getMainHoardHeap() {
    alignas(std::max_align_t) static char thBuf[sizeof(Hoard::HoardHeapType)];
    static auto *th = new (thBuf) Hoard::HoardHeapType;
    return th;
  }

 public:
  static constexpr size_t Alignment = alignof(std::max_align_t);

  ScaleneBaseHeap() : super(getMainHoardHeap()) {}
};

class BaseHeap : public HL::OneHeap<ScaleneBaseHeap> {
 public:
  void *memalign(size_t alignment, size_t size) {
    // XXX Copied from Heap-Layers/wrappers/generic-memalign.cpp ; we can't use
    // it directly because it invokes xxmalloc, which would be detected as a
    // recursive malloc call, causing all memalign to be serviced by
    // heapredirect's static buffer.  We use this->malloc() and this->free() to
    // ensure these are bound to this heap's functions.

    // Check for non power-of-two alignment.
    if ((alignment == 0) || (alignment & (alignment - 1))) {
      return nullptr;
    }

    if (alignment <= alignof(max_align_t)) {
      // Already aligned by default.
      return this->malloc(size);
    }

    // Try to just allocate an object of the requested size.
    // If it happens to be aligned properly, just return it.
    void *ptr = this->malloc(size);
    if (((size_t)ptr & ~(alignment - 1)) == (size_t)ptr) {
      // It is already aligned just fine; return it.
      return ptr;
    }
    // It was not aligned as requested: free the object and allocate a big one,
    // and align within.
    this->free(ptr);
    ptr = this->malloc(size + 2 * alignment);
    void *alignedPtr =
        (void *)(((size_t)ptr + alignment - 1) & ~(alignment - 1));
    return alignedPtr;
  }
};

#else  // not __APPLE__

using BaseHeap = HL::SysMallocHeap;

#endif

// For use by the replacement printf routines (see
// https://github.com/mpaland/printf)
extern "C" void _putchar(char ch) { int ignored = ::write(1, (void *)&ch, 1); }

constexpr uint64_t MallocSamplingRate = 870173ULL;
//  1048571ULL * 4;  // a prime number near a megabyte
constexpr uint64_t FreeSamplingRate = 758201ULL;
//  1048571ULL * 4;  // a prime number near a megabyte
constexpr uint64_t MemcpySamplingRate = 2097169ULL;  // another prime, near 2MB

class CustomHeapType : public HL::ThreadSpecificHeap<SampleHeap<MallocSamplingRate, FreeSamplingRate, BaseHeap>> {
 public:
  void lock() {}
  void unlock() {}
};

HEAP_REDIRECT(CustomHeapType, 8 * 1024 * 1024);

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

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif
