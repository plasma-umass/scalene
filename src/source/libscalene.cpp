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

#if 1

using BaseHeap = HL::SysMallocHeap;

#else // for debugging

class BaseHeap : public HL::SysMallocHeap {
public:
  using HL::SysMallocHeap::SysMallocHeap;

  void * malloc(size_t sz) {
    if (sz >= 256 * 1024) {
      printf("malloc %lu\n", sz);
    }
    return HL::SysMallocHeap::malloc(sz);
  }
};
#endif

// For use by the replacement printf routines (see
// https://github.com/mpaland/printf)
extern "C" void _putchar(char ch) { int ignored = ::write(1, (void *)&ch, 1); }

//constexpr uint64_t MallocSamplingRate = 262147ULL; // 870173ULL;
constexpr uint64_t MallocSamplingRate = 870173ULL;
//  1048571ULL * 4;  // a prime number near 256K
//constexpr uint64_t FreeSamplingRate = 262261ULL; // 758201ULL;
constexpr uint64_t FreeSamplingRate = 758201ULL;
//  1048571ULL * 4;  // a prime number near 256K
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

// Initial support for tracking mmap and munmap of arenas to enable correct use of pymalloc.
//
// TODO: walk the stack to verify that this is a Python-allocated
// arena -- a call to alloc(ctx, size) should be sufficiently
// disambiguating. See
// https://docs.python.org/3/c-api/memory.html#customize-pymalloc-arena-allocator
// For now, assume that all exactly 256MB requests for the
// right kind of memory (private, anonymous, etc.) are in fact Python
// arenas. See
// https://docs.python.org/3/c-api/memory.html#the-pymalloc-allocator).

#if 0 //!defined(_WIN32)

extern "C" {
  
  ATTRIBUTE_EXPORT void * LOCAL_PREFIX(mmap)(void *addr, size_t len, int prot, int flags, int fd, off_t offset) {
#if defined(__APPLE__)
    auto ptr = ::mmap(addr, len, prot, flags, fd, offset);
#else
    static auto * _mmap = reinterpret_cast<decltype(::mmap) *>(reinterpret_cast<size_t>(dlsym(RTLD_NEXT, "mmap")));
    auto ptr = _mmap(addr, len, prot, flags, fd, offset);
#endif
    if ((addr == NULL) &&
	(prot == (PROT_READ | PROT_WRITE)) &&
	(flags == (MAP_PRIVATE | MAP_ANONYMOUS)) &&
	(fd == -1) &&
	(offset == 0) &&
	(len == 256 * 1024))
      {
	TheHeapWrapper::register_malloc(len, 0);
      } else {
    }
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
    static auto * _munmap = reinterpret_cast<decltype(::munmap) *>(reinterpret_cast<size_t>(dlsym(RTLD_NEXT, "munmap")));
    auto result = _munmap(addr, len);
#endif
     if (len == (256 * 1024)) {
       TheHeapWrapper::register_free(len, 0);
     } else {
       //       printf("munmap %llu, %p\n", len, addr);
     }       
    return result;
  }

}
#endif

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
MAC_INTERPOSE(xxmmap, mmap);
MAC_INTERPOSE(xxmunmap, munmap);
#endif

