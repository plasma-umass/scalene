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

#include "common.hpp"
#include "heapredirect.h"
#include "memcpysampler.hpp"
#include "sampleheap.hpp"

#if defined(__APPLE__)
#include "macinterpose.h"
#endif

// Allocate exactly one system heap.
using BaseHeap = HL::OneHeap<HL::SysMallocHeap>;

// For use by the replacement printf routines (see
// https://github.com/mpaland/printf)
extern "C" void _putchar(char ch) { int ignored = ::write(1, (void *)&ch, 1); }

constexpr uint64_t MallocSamplingRate = 2 * 1048576ULL;
constexpr uint64_t FreeSamplingRate = MallocSamplingRate;
constexpr uint64_t MemcpySamplingRate = MallocSamplingRate * 7;

class CustomHeapType : public HL::ThreadSpecificHeap<SampleHeap<MallocSamplingRate, FreeSamplingRate, BaseHeap>> {
  using super = HL::ThreadSpecificHeap<SampleHeap<MallocSamplingRate, FreeSamplingRate, BaseHeap>>;
 public:
  void * malloc(size_t sz) {
    auto ptr = super::malloc(sz);
    return ptr;
  }
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

// Intercept arena allocation for tracking when using the (fast, built-in) pymalloc allocator.

#if !defined(_WIN32)

// Use the wrapped version of dlsym that sidesteps its nasty habit of trying to allocate memory.
extern "C" void * my_dlsym(void *, const char*);

extern "C" void * arena_malloc(void *, size_t len) {
#if defined(__APPLE__)
  auto ptr = ::mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
#else
  static auto * _mmap = reinterpret_cast<decltype(::mmap) *>(reinterpret_cast<size_t>(my_dlsym(RTLD_NEXT, "mmap")));
  auto ptr = _mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
#endif
  TheHeapWrapper::register_malloc(len, 0);
  return ptr;
}

extern "C" void arena_free(void *, void * addr, size_t len) {
#if defined(__APPLE__)
  auto result = ::munmap(addr, len);
#else
  static auto * _munmap = reinterpret_cast<decltype(::munmap) *>(reinterpret_cast<size_t>(my_dlsym(RTLD_NEXT, "munmap")));
  auto result = _munmap(addr, len);
#endif
  TheHeapWrapper::register_free(len, 0);
}

#include <Python.h>

class MakeArenaAllocator {
public:
  MakeArenaAllocator()
  {
    static PyObjectArenaAllocator arenaAlloc;
    
    arenaAlloc.ctx = nullptr;
    arenaAlloc.alloc = arena_malloc;
    arenaAlloc.free = arena_free;
    PyObject_SetArenaAllocator(&arenaAlloc);
  }
};

#if 0
extern "C" int makeArenaAllocator() {
  static MakeArenaAllocator m;
  return 1;
}
#endif

MakeArenaAllocator m;


#if 0
extern "C" {

  ATTRIBUTE_EXPORT void * LOCAL_PREFIX(mmap)(void *addr, size_t len, int prot, int flags, int fd, off_t offset) {
    if ((addr == NULL) &&
	(prot == (PROT_READ | PROT_WRITE)) &&
	(flags == (MAP_PRIVATE | MAP_ANONYMOUS)) &&
	(fd == -1) &&
	(offset == 0) &&
	(len == 256 * 1024))
      {
	TheHeapWrapper::register_malloc(len, 0);
      }
    
#if defined(__APPLE__)
    auto ptr = ::mmap(addr, len, prot, flags, fd, offset);
#else
    static auto * _mmap = reinterpret_cast<decltype(::mmap) *>(reinterpret_cast<size_t>(my_dlsym(RTLD_NEXT, "mmap")));
    auto ptr = _mmap(addr, len, prot, flags, fd, offset);
#endif
    return ptr;
  }

  ATTRIBUTE_EXPORT void * LOCAL_PREFIX(mmap64)(void *addr, size_t len, int prot, int flags, int fd, off_t offset) {
    auto ptr = LOCAL_PREFIX(mmap)(addr, len, prot, flags, fd, offset);
    return ptr;
  }
  
  ATTRIBUTE_EXPORT int LOCAL_PREFIX(munmap)(void * addr, size_t len) {
#if defined(__APPLE__)
    auto result = ::munmap(addr, len);
#else
    static auto * _munmap = reinterpret_cast<decltype(::munmap) *>(reinterpret_cast<size_t>(my_dlsym(RTLD_NEXT, "munmap")));
    auto result = _munmap(addr, len);
#endif
     if (len == (256 * 1024)) {
       TheHeapWrapper::register_free(len, 0);
     } else {
     }       
    return result;
  }

}
#endif

#endif

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
//MAC_INTERPOSE(xxmmap, mmap);
//MAC_INTERPOSE(xxmunmap, munmap);
#endif

