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
#include "scaleneheader.hpp"

#if defined(__APPLE__)
#include "macinterpose.h"
#endif

// Allocate exactly one system heap.
using BaseHeap = HL::OneHeap<HL::SysMallocHeap>;

// For use by the replacement printf routines (see
// https://github.com/mpaland/printf)
extern "C" void _putchar(char ch) { ::write(1, (void *)&ch, 1); }

constexpr uint64_t DefaultAllocationSamplingRate =
    1 * 1549351ULL;  // 1 * 1048576ULL;
constexpr uint64_t MemcpySamplingRate = DefaultAllocationSamplingRate * 7;

/**
 * @brief the replacement heap for sampling purposes
 *
 */
class CustomHeapType
    : public HL::ThreadSpecificHeap<
          SampleHeap<DefaultAllocationSamplingRate, BaseHeap>> {
  using super = HL::ThreadSpecificHeap<
      SampleHeap<DefaultAllocationSamplingRate, BaseHeap>>;

 public:
  void lock() {}
  void unlock() {}
};

HEAP_REDIRECT(CustomHeapType, 8 * 1024 * 1024);

/**
 * @brief Get the static MemcpySampler object
 *
 * @return auto& the singleton sampling object
 */
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

// Intercept local allocation for tracking when using the (fast, built-in)
// pymalloc allocator.

#if !defined(_WIN32)

#include <Python.h>

#define USE_HEADERS 1
#define DEBUG_HEADER 0

#define DL_FUNCTION(name) \
  static decltype(name) *dl##name = (decltype(name) *)dlsym(RTLD_DEFAULT, #name)

// Maximum size allocated internally by pymalloc;
// aka "SMALL_REQUEST_THRESHOLD" in cpython/Objects/obmalloc.c
#define PYMALLOC_MAX_SIZE 512

/**
 * @brief replace local Python allocators with our own sampling variants
 *
 * @tparam Domain the Python domain of allocator we replace
 */

template <PyMemAllocatorDomain Domain>
class MakeLocalAllocator {
 public:
  MakeLocalAllocator() {
    localAlloc = {.ctx = nullptr,
                  .malloc = local_malloc,
                  .calloc = local_calloc,
                  .realloc = local_realloc,
                  .free = local_free};

    DL_FUNCTION(PyMem_GetAllocator);
    DL_FUNCTION(PyMem_SetAllocator);

    if (dlPyMem_GetAllocator != nullptr && dlPyMem_SetAllocator != nullptr) {
      // if these aren't found, chances are we were preloaded onto something
      // other than Python
      dlPyMem_GetAllocator(Domain, get_original_allocator());
      dlPyMem_SetAllocator(Domain, &localAlloc);
    }
  }

 private:
  /// @brief the actual allocator we use to satisfy object allocations
  PyMemAllocatorEx localAlloc;

  static inline PyMemAllocatorEx *get_original_allocator() {
    // poor man's "static inline" member
    static PyMemAllocatorEx original_allocator;
    return &original_allocator;
  }

  static inline void *local_malloc(void *ctx, size_t len) {
#if 1
    // Ensure all allocation requests are multiples of eight,
    // mirroring the actual allocation sizes employed by pymalloc
    // (See https://github.com/python/cpython/blob/main/Objects/obmalloc.c#L807)
    if (len <= PYMALLOC_MAX_SIZE) {
      if (unlikely(len == 0)) {
        // Handle 0.
        len = 8;
      }
      len = (len + 7) & ~7;
    }
#endif
#if USE_HEADERS
    void *buf = nullptr;
    const auto allocSize = len + sizeof(ScaleneHeader);
    buf = get_original_allocator()->malloc(ctx, allocSize);
    auto *header = new (buf) ScaleneHeader(len);
#else
    auto *header = (ScaleneHeader *)get_original_allocator()->malloc(ctx, len);
#endif
    assert(header);                  // We expect this to always succeed.
    if (len <= PYMALLOC_MAX_SIZE) {  // don't count allocations pymalloc passes
                                     // to malloc
      TheHeapWrapper::register_malloc(len, ScaleneHeader::getObject(header));
    }
    class Nada {};
    static_assert(
        SampleHeap<1, HL::NullHeap<Nada>>::NEWLINE > PYMALLOC_MAX_SIZE,
        "NEWLINE must be greater than PYMALLOC_MAX_SIZE.");
    if (len == SampleHeap<1, HL::NullHeap<Nada>>::NEWLINE) {
      // Special case: register the new line execution.
      TheHeapWrapper::register_malloc(len, ScaleneHeader::getObject(header));
    }
#if USE_HEADERS
    assert((size_t)ScaleneHeader::getObject(header) - (size_t)header >=
           sizeof(ScaleneHeader));
#ifndef NDEBUG
    if (ScaleneHeader::getSize(ScaleneHeader::getObject(header)) < len) {
      printf_("Size mismatch: %lu %lu\n",
              ScaleneHeader::getSize(ScaleneHeader::getObject(header)), len);
    }
#endif
    assert(ScaleneHeader::getSize(ScaleneHeader::getObject(header)) >= len);
#endif
    return ScaleneHeader::getObject(header);
  }

  static inline void local_free(void *ctx, void *ptr) {
    // ignore nullptr
    if (ptr) {
      // printf_("LOCAL FREE %d (%d)\n", Domain, local_allocator_count);
      const auto sz = ScaleneHeader::getSize(ptr);
      if (sz <= PYMALLOC_MAX_SIZE) {
        TheHeapWrapper::register_free(sz, ptr);
      }
      get_original_allocator()->free(ctx, ScaleneHeader::getHeader(ptr));
    }
  }

  static inline void *local_realloc(void *ctx, void *ptr, size_t new_size) {
    if (new_size < 8) {
      new_size = 8;
    }
    if (!ptr) {
      return local_malloc(ctx, new_size);
    }
    const auto sz = ScaleneHeader::getSize(ptr);

    // printf_("LOCAL REALLOC %d (%lu)\n", Domain, new_size);

    void *p = nullptr;
    const auto allocSize = new_size + sizeof(ScaleneHeader);
    void *buf = get_original_allocator()->realloc(
        ctx, ScaleneHeader::getHeader(ptr), allocSize);
    ScaleneHeader *result = new (buf) ScaleneHeader(new_size);
    if (result) {
      if (sz < new_size) {
        if (new_size - sz <= PYMALLOC_MAX_SIZE) {
          TheHeapWrapper::register_malloc(new_size - sz,
                                          ScaleneHeader::getObject(result));
        }
      } else if (sz > new_size) {
        if (sz - new_size <= PYMALLOC_MAX_SIZE) {
          TheHeapWrapper::register_free(sz - new_size, ptr);
        }
      }
    }
    ScaleneHeader::setSize(ScaleneHeader::getObject(result), new_size);
    p = ScaleneHeader::getObject(result);
    return p;
  }

  static inline void *local_calloc(void *ctx, size_t nelem, size_t elsize) {
    // printf_("CALLOC %lu %lu\n", nelem, elsize);
    const auto nbytes = nelem * elsize;
    void *obj = local_malloc(ctx, nbytes);
    if (true) {  // obj) {
      memset(obj, 0, nbytes);
    }
    return obj;
  }

 private:
  static constexpr size_t MAGIC_NUMBER = 0x01020304;
};

// from pywhere.hpp
decltype(p_whereInPython) __attribute((visibility("default")))
p_whereInPython{nullptr};

static MakeLocalAllocator<PYMEM_DOMAIN_MEM> l_mem;
static MakeLocalAllocator<PYMEM_DOMAIN_OBJ> l_obj;

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif

#endif
