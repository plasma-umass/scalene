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

// Intercept local allocation for tracking when using the (fast, built-in) pymalloc allocator.

#if !defined(_WIN32)

#include <Python.h>

#define USE_HEADERS 1
#define DEBUG_HEADER 0

template <PyMemAllocatorDomain Domain>
class MakeLocalAllocator {
public:
  
  MakeLocalAllocator()
  {
    localAlloc = {
      .ctx = nullptr,
      .malloc = local_malloc,
      .calloc = local_calloc,
      .realloc = local_realloc,
      .free = local_free
    };
    PyMem_GetAllocator(Domain, &original_allocator);
    PyMem_SetAllocator(Domain, &localAlloc);
  }

  ~MakeLocalAllocator() {
    PyMem_SetAllocator(Domain, &original_allocator);
  }

private:

  PyMemAllocatorEx localAlloc;
  static inline PyMemAllocatorEx original_allocator;
  
  static void * local_malloc(void * ctx, size_t len) {
    ///    printf_("MALLOC %lu\n", len);
    if (len < 8) {
      len = 8;
    }
    Header * header = new (original_allocator.malloc(ctx, len + 8 + sizeof(Header))) Header(len);
    if (header) {
      //      setSize(getObject(header), len);
      TheHeapWrapper::register_malloc(len, getObject(header));
#if USE_HEADERS
      assert((size_t) getObject(header) - (size_t) header >= sizeof(Header));
      if (getSize(getObject(header)) < len) {
	printf_("WTF %lu %lu\n", getSize(getObject(header)), len);
      }
      assert(getSize(getObject(header)) >= len);
#endif
      return getObject(header);
    }
    return nullptr;
  }

  static void local_free(void * ctx, void * ptr) {
    ///    printf_("FREE %p\n", ptr);
    if (ptr) {
      const auto sz = getSize(ptr);
      TheHeapWrapper::register_free(sz, ptr);
      original_allocator.free(ctx, getHeader(ptr));
    }
  }

  static void * local_realloc(void * ctx, void * ptr, size_t new_size) {
    //    printf_("REALLOC %p %lu\n", ptr, new_size);
    if (new_size < 8) {
      new_size = 8;
    }
    if (!ptr) {
      return local_malloc(ctx, new_size);
    }
    const auto sz = getSize(ptr);
    TheHeapWrapper::register_free(sz, getHeader(ptr));
    Header * result = (Header *) original_allocator.realloc(ctx, getHeader(ptr), new_size + 8 + sizeof(Header));
    if (result) {
      TheHeapWrapper::register_malloc(new_size, getObject(result));
      setSize(getObject(result), new_size);
      return getObject(result);
    }
    return nullptr;
  }

  static void * local_calloc(void * ctx, size_t nelem, size_t elsize) {
    // printf_("CALLOC %lu %lu\n", nelem, elsize);
    void * obj = local_malloc(ctx, nelem * elsize);
    if (obj) {
      memset(obj, 0, nelem * elsize);
    }
    return obj;
  }

private:

  static constexpr size_t MAGIC_NUMBER = 0x01020304;
  
#if USE_HEADERS
#if DEBUG_HEADER
  class Header {
  public:
    Header(size_t sz)
      : size(sz),
	magic(MAGIC_NUMBER)
    {}
    alignas(std::max_align_t) size_t size;
    size_t magic;
  };
#else
  class Header {
  public:
    Header(size_t sz)
      : size(sz)
    {}
    alignas(std::max_align_t) size_t size;
  };
#endif
#else
  class Header {};
#endif
  
  static size_t getSize(void * ptr) {
#if USE_HEADERS
#if DEBUG_HEADER
    assert(getHeader(ptr)->magic == MAGIC_NUMBER);
#endif
    auto sz = getHeader(ptr)->size;
    if (sz > 512) {
#if defined(__APPLE__)
      //      printf_("%p: sz = %lu, actual size = %lu\n", getHeader(ptr), sz, ::malloc_size(getHeader(ptr)));
      assert(::malloc_size(getHeader(ptr)) >= sz);
#else
      assert(::malloc_usable_size(getHeader(ptr)) >= sz);
#endif
    }
    return sz;
#else
    return 123; // Bogus size.
#endif
  }

  static void setSize(void * ptr, size_t sz) {
#if USE_HEADERS
    auto h = getHeader(ptr);
#if DEBUG_HEADER
    h->magic = MAGIC_NUMBER;
#endif
    h->size = sz;
#endif
  }
  
  static Header * getHeader(void * ptr) {
#if USE_HEADERS
    return (Header *) ptr - 1;
#else
    return (Header *) ptr;
#endif
  }

  static void * getObject(Header * header) {
#if USE_HEADERS
    return (void *) (header + 1);
#else
    return (void *) header;
#endif
  }

};


static MakeLocalAllocator<PYMEM_DOMAIN_MEM> l_mem;
static MakeLocalAllocator<PYMEM_DOMAIN_OBJ> l_obj;

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif

#endif
