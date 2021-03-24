#define SCALENE_DISABLE_SIGNALS 0  // for debugging only

#include <execinfo.h>
#include <heaplayers.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "common.hpp"
#include "heapredirect.hpp"
#include "memcpysampler.hpp"
#include "sampleheap.hpp"
#include "stprintf.h"
#include "sysmallocheap.hpp"
#include "tprintf.h"

#if defined(__APPLE__)
#include "macinterpose.h"
#endif

const uint64_t MallocSamplingRate = 1048576ULL;
const uint64_t MemcpySamplingRate = MallocSamplingRate * 2ULL;

class CustomHeapType : public HL::ThreadSpecificHeap<
                           SampleHeap<MallocSamplingRate, SysMallocHeap>> {
 public:
  void lock() {}
  void unlock() {}
};

HEAP_REDIRECT(CustomHeapType, 8 * 1024 * 1024);

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

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif
