#define SCALENE_DISABLE_SIGNALS 0  // for debugging only

#include <heaplayers.h>

#include <execinfo.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "stprintf.h"
#include "tprintf.h"
#include "common.hpp"

#include "sampleheap.hpp"
#include "memcpysampler.hpp"

#if defined(__APPLE__)
#include "macinterpose.h"
#include "tprintf.h"
#endif

const uint64_t MallocSamplingRate = 1048576ULL;
const uint64_t MemcpySamplingRate = MallocSamplingRate * 2ULL;

#include "nextheap.hpp"

class ParentHeap: public HL::ThreadSpecificHeap<SampleHeap<MallocSamplingRate, NextHeap>> {};

class CustomHeapType : public ParentHeap {
public:
  void lock() {}
  void unlock() {}
};

//typedef NextHeap CustomHeapType;

// This is a hack to have a long-living buffer
// to put init filename in
char init_file[MAX_BUFSIZE];
char* init_with_pid() {
  stprintf::stprintf(init_file, "/tmp/initializer-@", getpid());
  // creates the file and then closes it
  return init_file;
  int fd = open(init_file, O_CREAT|O_RDWR, S_IRUSR | S_IWUSR);
  close(fd);
  return init_file;
}
char* SampleFile::initializer = init_with_pid();
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
HL::PosixLock SampleFile::lock;

#if 1

static CustomHeapType thang;
#define getTheCustomHeap() thang

#else

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

extern "C" ATTRIBUTE_EXPORT void * xxmemalign(size_t alignment, size_t sz) {
  return getTheCustomHeap().memalign(alignment, sz);
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
