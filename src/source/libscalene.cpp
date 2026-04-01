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
    1 * 10485767ULL;  // was 1 * 1549351ULL;
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

#define DL_FUNCTION(name) \
  static decltype(name) *dl##name = (decltype(name) *)dlsym(RTLD_DEFAULT, #name)

// Maximum size allocated internally by pymalloc;
// aka "SMALL_REQUEST_THRESHOLD" in cpython/Objects/obmalloc.c
#define PYMALLOC_MAX_SIZE 512

/**
 * @brief Double-buffered allocator storage for atomic swap.
 *
 * Allows updating the "original" allocator (e.g., when Py_Initialize
 * resets it) without tearing — readers always see a consistent struct.
 */
struct OriginalAllocatorStorage {
  PyMemAllocatorEx buffers[2];
  std::atomic<int> idx{0};

  PyMemAllocatorEx* current() {
    return &buffers[idx.load(std::memory_order_acquire)];
  }

  void update(const PyMemAllocatorEx* alloc) {
    int new_idx = 1 - idx.load(std::memory_order_relaxed);
    buffers[new_idx] = *alloc;  // Copy to inactive buffer
    idx.store(new_idx, std::memory_order_release);  // Atomic swap
  }
};

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

    auto real_get = get_real_PyMem_GetAllocator();
    auto real_set = get_real_PyMem_SetAllocator();

    if (real_get != nullptr && real_set != nullptr) {
      // Save the current (pre-init) allocator as the original
      real_get(Domain, get_originals().current());
      // Install our wrapper via the REAL SetAllocator (bypassing interposition)
      real_set(Domain, &localAlloc);
      _installed = true;
    }
  }

  static bool is_installed() { return _installed; }

  static OriginalAllocatorStorage& get_originals() {
    static OriginalAllocatorStorage storage;
    return storage;
  }

  // Get the real (non-interposed) PyMem_GetAllocator
  static auto get_real_PyMem_GetAllocator() {
    static auto fn = (decltype(PyMem_GetAllocator)*)dlsym(RTLD_NEXT, "PyMem_GetAllocator");
    return fn;
  }

  // Get the real (non-interposed) PyMem_SetAllocator
  static auto get_real_PyMem_SetAllocator() {
    static auto fn = (decltype(PyMem_SetAllocator)*)dlsym(RTLD_NEXT, "PyMem_SetAllocator");
    return fn;
  }

 private:
  /// @brief the actual allocator we use to satisfy object allocations
  PyMemAllocatorEx localAlloc;
  static inline bool _installed = false;

  static inline void *local_malloc(void *ctx, size_t len) {
    MallocRecursionGuard m;
#ifdef Py_GIL_DISABLED
    // On free-threaded Python, we cannot prepend ScaleneHeader because the
    // GC directly scans mimalloc heap pages expecting valid Python objects.
    // Track allocations without modifying them.
    auto* orig = get_originals().current();
    void *ptr = orig->malloc(orig->ctx, len);
    if (ptr && !m.wasInMalloc()) {
      TheHeapWrapper::register_malloc(len, ptr);
    }
    return ptr;
#else
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
    auto* orig = get_originals().current();
    buf = orig->malloc(orig->ctx, allocSize);
    auto *header = new (buf) ScaleneHeader(len);
    class Nada {};
#else
    auto* orig = get_originals().current();
    auto *header = (ScaleneHeader *)orig->malloc(orig->ctx, len);
#endif
    assert(header);  // We expect this to always succeed.
    if (!m.wasInMalloc()) {
      TheHeapWrapper::register_malloc(len, ScaleneHeader::getObject(header));
    }

    static_assert(
        SampleHeap<1, HL::NullHeap<Nada>>::NEWLINE > PYMALLOC_MAX_SIZE,
        "NEWLINE must be greater than PYMALLOC_MAX_SIZE.");
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
#endif  // Py_GIL_DISABLED
  }

  static inline void local_free(void *ctx, void *ptr) {
    // ignore nullptr
    if (ptr) {
      MallocRecursionGuard m;
#ifdef Py_GIL_DISABLED
      if (!m.wasInMalloc()) {
        // We don't have ScaleneHeader on free-threaded Python, so we
        // can't recover the exact size. Use 0 for sampling purposes.
        TheHeapWrapper::register_free(0, ptr);
      }
      auto* orig = get_originals().current();
      orig->free(orig->ctx, ptr);
#else
      const auto sz = ScaleneHeader::getSize(ptr);

      if (!m.wasInMalloc()) {
        TheHeapWrapper::register_free(sz, ptr);
      }
      auto* orig = get_originals().current();
      orig->free(orig->ctx, ScaleneHeader::getHeader(ptr));
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
#ifdef Py_GIL_DISABLED
    MallocRecursionGuard m;
    auto* orig = get_originals().current();
    void *result = orig->realloc(orig->ctx, ptr, new_size);
    if (result && !m.wasInMalloc()) {
      TheHeapWrapper::register_malloc(new_size, result);
    }
    return result;
#else
    MallocRecursionGuard m;
    const auto sz = ScaleneHeader::getSize(ptr);
    void *p = nullptr;
    const auto allocSize = new_size + sizeof(ScaleneHeader);
    auto* orig = get_originals().current();
    void *buf = orig->realloc(orig->ctx,
                              ScaleneHeader::getHeader(ptr),
                              allocSize);
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
    p = ScaleneHeader::getObject(result);
    return p;
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

 private:
  static constexpr size_t MAGIC_NUMBER = 0x01020304;
};

// from pywhere.hpp
decltype(p_whereInPython)
    __attribute((visibility("default"))) p_whereInPython{nullptr};

std::atomic_bool __attribute((visibility("default"))) p_scalene_done{true};

static MakeLocalAllocator<PYMEM_DOMAIN_MEM> l_mem;
static MakeLocalAllocator<PYMEM_DOMAIN_OBJ> l_obj;

// Interpose on PyMem_SetAllocator to prevent Py_Initialize from overwriting
// our allocator wrapper. When CPython tries to set a new allocator, we
// atomically update the "original" that our wrapper delegates to, but keep
// our wrapper installed. This avoids calling PyMem_SetAllocator after init
// (which is not thread-safe) while ensuring our wrapper survives init.
extern "C" __attribute__((visibility("default")))
void PyMem_SetAllocator(PyMemAllocatorDomain domain, PyMemAllocatorEx *allocator) {
  if (domain == PYMEM_DOMAIN_MEM && l_mem.is_installed()) {
    // Atomically update the original allocator our wrapper delegates to
    l_mem.get_originals().update(allocator);
    return;  // Keep our wrapper installed
  }
  if (domain == PYMEM_DOMAIN_OBJ && l_obj.is_installed()) {
    l_obj.get_originals().update(allocator);
    return;
  }
  // For other domains or before our wrapper is installed, pass through
  auto real_set = MakeLocalAllocator<PYMEM_DOMAIN_MEM>::get_real_PyMem_SetAllocator();
  if (real_set) {
    real_set(domain, allocator);
  }
}

// Also interpose PyMem_GetAllocator so CPython sees the "intended" allocator,
// not our wrapper. This prevents confusion in debug/diagnostic code.
extern "C" __attribute__((visibility("default")))
void PyMem_GetAllocator(PyMemAllocatorDomain domain, PyMemAllocatorEx *allocator) {
  if (domain == PYMEM_DOMAIN_MEM && l_mem.is_installed()) {
    *allocator = *l_mem.get_originals().current();
    return;
  }
  if (domain == PYMEM_DOMAIN_OBJ && l_obj.is_installed()) {
    *allocator = *l_obj.get_originals().current();
    return;
  }
  auto real_get = MakeLocalAllocator<PYMEM_DOMAIN_MEM>::get_real_PyMem_GetAllocator();
  if (real_get) {
    real_get(domain, allocator);
  }
}

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
MAC_INTERPOSE(xxmemmove, memmove);
MAC_INTERPOSE(xxstrcpy, strcpy);
#endif

#endif
