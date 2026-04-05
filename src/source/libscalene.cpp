#define SCALENE_DISABLE_SIGNALS 0  // for debugging only

#if !defined(_WIN32)
#include <unistd.h>
#endif

// Include C++ standard headers FIRST, before any vendor headers that might
// define macros conflicting with standard library functions (e.g., printf.h
// defines vsnprintf -> vsnprintf_ which breaks std::vsnprintf in <string>).
#include <cstddef>
#include <string>

#include <heaplayers.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>

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
    1 * 10485767ULL;  // ~10 MB sampling window
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
#include "sharded_size_map.hpp"

#define DL_FUNCTION(name) \
  static decltype(name) *dl##name = (decltype(name) *)dlsym(RTLD_DEFAULT, #name)

#ifdef Py_GIL_DISABLED
static ShardedSizeMap g_size_map;
#endif

// Maximum size allocated internally by pymalloc;
// aka "SMALL_REQUEST_THRESHOLD" in cpython/Objects/obmalloc.c
#define PYMALLOC_MAX_SIZE 512

/**
 * @brief replace local Python allocators with our own sampling variants
 *
 * @tparam Domain the Python domain of allocator we replace
 *
 * On regular Python, uses ScaleneHeader (16-byte inline header) for
 * O(1) size recovery — just pointer arithmetic, no locks or hashing.
 * On free-threaded Python, uses ShardedSizeMap (out-of-band hash table)
 * because prepending headers breaks GC page scanning.
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
      dlPyMem_GetAllocator(Domain, get_original_allocator());
      dlPyMem_SetAllocator(Domain, &localAlloc);
    }
  }

  // Re-install allocator wrappers. Called after Py_Initialize to handle
  // runtimes (e.g. free-threaded Python) that reset allocators during init.
  void reinstall(decltype(PyMem_GetAllocator)* getter,
                 decltype(PyMem_SetAllocator)* setter) {
    PyMemAllocatorEx current;
    getter(Domain, &current);
    if (current.malloc != local_malloc) {
      getter(Domain, get_original_allocator());
      setter(Domain, &localAlloc);
    }
  }

 private:
  /// @brief the actual allocator we use to satisfy object allocations
  PyMemAllocatorEx localAlloc;

  static inline PyMemAllocatorEx *get_original_allocator() {
    static PyMemAllocatorEx original_allocator;
    return &original_allocator;
  }

  static inline void *local_malloc(void *ctx, size_t len) {
    MallocRecursionGuard m;
#ifdef Py_GIL_DISABLED
    // Free-threaded: track size out-of-band via sharded hash table.
    void *ptr = get_original_allocator()->malloc(
        get_original_allocator()->ctx, len);
    if (ptr && !m.wasInMalloc()) {
      g_size_map.insert(ptr, len);
      TheHeapWrapper::register_malloc(len, ptr);
    }
    return ptr;
#else
    // Regular Python: prepend ScaleneHeader for O(1) size recovery.
    if (len <= PYMALLOC_MAX_SIZE) {
      if (unlikely(len == 0)) {
        len = 8;
      }
      len = (len + 7) & ~7;
    }
    const auto allocSize = len + sizeof(ScaleneHeader);
    void *buf = get_original_allocator()->malloc(
        get_original_allocator()->ctx, allocSize);
    auto *header = new (buf) ScaleneHeader(len);
    if (!m.wasInMalloc()) {
      TheHeapWrapper::register_malloc(len, ScaleneHeader::getObject(header));
    }
    return ScaleneHeader::getObject(header);
#endif
  }

  static inline void local_free(void *ctx, void *ptr) {
    if (ptr) {
      MallocRecursionGuard m;
#ifdef Py_GIL_DISABLED
      const auto sz = g_size_map.remove(ptr);
      if (!m.wasInMalloc()) {
        TheHeapWrapper::register_free(sz, ptr);
      }
      get_original_allocator()->free(get_original_allocator()->ctx, ptr);
#else
      const auto sz = ScaleneHeader::getSize(ptr);
      if (!m.wasInMalloc()) {
        TheHeapWrapper::register_free(sz, ptr);
      }
      get_original_allocator()->free(get_original_allocator()->ctx,
                                     ScaleneHeader::getHeader(ptr));
#endif
    }
  }

  static inline void *local_realloc(void *ctx, void *ptr, size_t new_size) {
    if (new_size < 8) {
      new_size = 8;
    }
    if (!ptr) {
      return local_malloc(ctx, new_size);
    }
    MallocRecursionGuard m;
#ifdef Py_GIL_DISABLED
    const auto old_size = g_size_map.remove(ptr);
    void *result = get_original_allocator()->realloc(
        get_original_allocator()->ctx, ptr, new_size);
    if (result) {
      if (!m.wasInMalloc()) {
        g_size_map.insert(result, new_size);
        if (new_size > old_size) {
          TheHeapWrapper::register_malloc(new_size - old_size, result);
        } else if (old_size > new_size) {
          TheHeapWrapper::register_free(old_size - new_size, ptr);
        }
      }
    }
    return result;
#else
    const auto sz = ScaleneHeader::getSize(ptr);
    const auto allocSize = new_size + sizeof(ScaleneHeader);
    void *buf = get_original_allocator()->realloc(
        get_original_allocator()->ctx,
        ScaleneHeader::getHeader(ptr), allocSize);
    ScaleneHeader *result = new (buf) ScaleneHeader(new_size);
    if (result && !m.wasInMalloc()) {
      if (sz < new_size) {
        TheHeapWrapper::register_malloc(new_size - sz,
                                        ScaleneHeader::getObject(result));
      } else if (sz > new_size) {
        TheHeapWrapper::register_free(sz - new_size, ptr);
      }
    }
    ScaleneHeader::setSize(ScaleneHeader::getObject(result), new_size);
    return ScaleneHeader::getObject(result);
#endif
  }

  static inline void *local_calloc(void *ctx, size_t nelem, size_t elsize) {
    const auto nbytes = nelem * elsize;
    void *obj = local_malloc(ctx, nbytes);
    if (obj) {
      memset(obj, 0, nbytes);
    }
    return obj;
  }

};

// from pywhere.hpp
decltype(p_whereInPython)
    __attribute((visibility("default"))) p_whereInPython{nullptr};

std::atomic_bool __attribute((visibility("default"))) p_scalene_done{true};

static MakeLocalAllocator<PYMEM_DOMAIN_MEM> l_mem;
static MakeLocalAllocator<PYMEM_DOMAIN_OBJ> l_obj;

// Re-install Scalene's allocator wrappers after Py_Initialize.
// Free-threaded Python (3.13t+) may reset allocators during init,
// overwriting our static-constructor setup. pywhere calls this
// from populate_struct() to ensure the allocators are in place.
extern "C" __attribute__((visibility("default")))
void scalene_reinstall_local_allocators() {
  DL_FUNCTION(PyMem_GetAllocator);
  DL_FUNCTION(PyMem_SetAllocator);

  if (dlPyMem_GetAllocator != nullptr && dlPyMem_SetAllocator != nullptr) {
    l_mem.reinstall(dlPyMem_GetAllocator, dlPyMem_SetAllocator);
    l_obj.reinstall(dlPyMem_GetAllocator, dlPyMem_SetAllocator);
  }
}

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif

#endif
