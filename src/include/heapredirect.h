/*

  Heap Layers: An Extensible Memory Allocation Infrastructure
  
  Copyright (C) 2000-2020 by Emery Berger
  http://www.emeryberger.com
  emery@cs.umass.edu
  
  Heap Layers is distributed under the terms of the Apache 2.0 license.

  You may obtain a copy of the License at
  http://www.apache.org/licenses/LICENSE-2.0

*/
#pragma once

#ifndef HL_HEAPREDIRECT_H
#define HL_HEAPREDIRECT_H 

#if !defined(likely)
  #define likely(x) __builtin_expect(!!(x), 1)
#endif
#if !defined(unlikely)
  #define unlikely(x) __builtin_expect(!!(x), 0)
#endif
#if !defined ATTRIBUTE_EXPORT
  #define ATTRIBUTE_EXPORT __attribute__((visibility("default")))
#endif

#include "printf.h"

namespace HL {

/**
 * Redirects the system heap calls to a custom heap, using Heap-Layers' wrappers.
 *
 * In order to service ::malloc through a custom heap, the custom heap's constructor
 * and its malloc method need to run; if either one of these, directly or indirectly,
 * need to call ::malloc, that would lead to an infinite recursion.  To avoid this, we
 * detect such recursive ::malloc calls using a thread-local boolean variable and service
 * them from a statically allocated heap.
 *
 * The thread-local variable's and the static heap's initialization must be done carefully
 * so as not to require ::malloc when no heap is available to service it from. To further
 * complicate things, ::malloc is/can be invoked early during executable startup, before
 * C++ constructors for global objects.  On MacOS, this seems to happen before thread
 * initialization: attempts to use thread_local or __thread lead to an abort() in _tlv_bootstrap.
 *
 * To work around the C++ constructor issue, we use static initializers within functions;
 * for the thread_local/__thread issue, we use POSIX thread-local data.  We prefer __atomic
 * calls to std::atomic because STL code feels more likely to invoke malloc.
 * We use std::recursive_mutex and std::lock_guard to avoid introducing more code and because
 * they don't seem to require malloc, but may need to move to pthread_mutex if that should change.
 *
 * The problem is really that "won't use malloc" AFAIK isn't part of most of these primitives'
 * contracts, so we stand on shaky ground.
 *
 * @author Juan Altmayer Pizzorno
 */

  // NOTE: The static heap functionality is currently disabled (as of 8/27/2021).
  
template<typename CustomHeapType, int STATIC_HEAP_SIZE> 
class HeapWrapper {
  typedef LockedHeap<std::mutex, StaticBufferHeap<STATIC_HEAP_SIZE>> StaticHeapType;

// Using a static bool is not thread safe, but gives us a benchmarking
// baseline for this implementation.
#define HW_USE_STATIC_BOOL 0

  static bool* getInMallocFlag() {
#if !HW_USE_STATIC_BOOL
    // modified double-checked locking pattern (https://en.wikipedia.org/wiki/Double-checked_locking)
    static enum {NEEDS_KEY=0, CREATING_KEY=1, DONE=2} inMallocKeyState{NEEDS_KEY};
    static pthread_key_t inMallocKey;
    static std::recursive_mutex m;

    auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_ACQUIRE);
    if (state != DONE) {
      std::lock_guard<decltype(m)> g{m};

      state = __atomic_load_n(&inMallocKeyState, __ATOMIC_RELAXED);
      if (unlikely(state == CREATING_KEY)) {
        return nullptr; // recursively invoked
      }
      else if (unlikely(state == NEEDS_KEY)) {
        __atomic_store_n(&inMallocKeyState, CREATING_KEY, __ATOMIC_RELAXED);
        if (pthread_key_create(&inMallocKey, 0) != 0) { // may call malloc/calloc/...
          abort();
        }
        __atomic_store_n(&inMallocKeyState, DONE, __ATOMIC_RELEASE);
      }
    }

    bool* flag = (bool*)pthread_getspecific(inMallocKey); // not expected to call malloc
    if (unlikely(flag == nullptr)) {
      std::lock_guard<decltype(m)> g{m};

      static bool initializing = false;
      if (initializing) {
        return nullptr; // recursively invoked
      }

      initializing = true;
      flag = (bool*)getHeap<StaticHeapType>()->malloc(sizeof(bool));
      *flag = false;
      if (pthread_setspecific(inMallocKey, flag) != 0) { // may call malloc/calloc/...
        abort();
      }
      initializing = false;
    }

    return flag;
#else
    static bool inMalloc = false;
    return &inMalloc;
#endif
  }

 public:
  template<class HEAP>
  static inline HEAP* getHeap() {
    // Allocate heap on first use and never destroy it, for malloc and such
    // may still be used in atexit() 
    alignas(std::max_align_t) static char buffer[sizeof(HEAP)];
    static HEAP* heap = new (buffer) HEAP;
    return heap;
  }

  static inline void* malloc(size_t sz) {
    auto ptr = getHeap<CustomHeapType>()->malloc(sz);
    assert(isValid(ptr));
    return ptr;
  }

  static inline void *memalign(size_t alignment, size_t sz) {
    auto ptr = getHeap<CustomHeapType>()->memalign(alignment, sz);
    assert(isValid(ptr));
    return ptr;
  }

  #if HL_USE_XXREALLOC
  static inline void* realloc(void * ptr, size_t sz) {
    auto buf = getHeap<CustomHeapType>()->realloc(ptr, sz);
    assert(isValid(buf));
    return buf;
  }
  #endif

  static inline bool isValid(void * ptr) {
#if !defined(__GLIBC__)
    (void) ptr;
    return true;
#else
    // Special handling for glibc, adapted from
    // https://sources.debian.org/src/glibc/2.31-17/malloc/malloc.c/
    if (!ptr) {
      return true;
    }
    enum {
      PREV_INUSE = 0x01,
      IS_MMAPPED = 0x02,
      NON_MAIN_ARENA = 0x04 };
    struct malloc_chunk {
      size_t mchunk_prev_size;
      size_t mchunk_size;
    };
    auto mchunk = (malloc_chunk *) ptr - 1;
    auto size = mchunk->mchunk_size & ~(PREV_INUSE | IS_MMAPPED | NON_MAIN_ARENA);
    if ((uintptr_t) ptr > (uintptr_t) -size) {
      return false;
    }
    return true;
#endif
  }
  
  static inline void free(void* ptr) {
    if (isValid(ptr)) {
      getHeap<CustomHeapType>()->free(ptr);
    }
  }

  static inline size_t getSize(void *ptr) {
    if (isValid(ptr)) {
      return getHeap<CustomHeapType>()->getSize(ptr);
    }
    return 0;
  }

  static inline void xxmalloc_lock() {
    getHeap<CustomHeapType>()->lock();
  }

  static inline void xxmalloc_unlock() {
    getHeap<CustomHeapType>()->unlock();
  }

  // For use with sampling allocation from https://github.com/plasma-umass/scalene
  static inline void register_malloc(size_t sz, void * ptr) {
    getHeap<CustomHeapType>()->register_malloc(sz, ptr);
  }

  static inline void register_free(size_t sz, void * ptr) {
    if (ptr) {
      getHeap<CustomHeapType>()->register_free(sz, ptr);
    }
  }

};

} // namespace

#if HL_USE_XXREALLOC
#define HEAP_REDIRECT(CustomHeap, staticSize)\
  typedef HL::HeapWrapper<CustomHeap, staticSize> TheHeapWrapper;\
  extern "C" {\
    ATTRIBUTE_EXPORT void *xxmalloc(size_t sz) {\
      return TheHeapWrapper::malloc(sz);\
    }\
    \
    ATTRIBUTE_EXPORT void xxfree(void *ptr) {\
      TheHeapWrapper::free(ptr);\
    }\
    \
    ATTRIBUTE_EXPORT void *xxmemalign(size_t alignment, size_t sz) {\
      return TheHeapWrapper::memalign(alignment, sz);\
    }\
    \
    ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void *ptr) {\
      return TheHeapWrapper::getSize(ptr);	\
    }\
    \
    ATTRIBUTE_EXPORT void xxmalloc_lock() {\
      TheHeapWrapper::xxmalloc_lock();\
    }\
    \
    ATTRIBUTE_EXPORT void xxmalloc_unlock() {\
      TheHeapWrapper::xxmalloc_unlock();\
    }\
    ATTRIBUTE_EXPORT void* xxrealloc(void * ptr, size_t sz) {\
      return TheHeapWrapper::realloc(ptr, sz); \
    }\
  }
#else
#define HEAP_REDIRECT(CustomHeap, staticSize)\
  typedef HL::HeapWrapper<CustomHeap, staticSize> TheHeapWrapper;\
  extern "C" {\
    ATTRIBUTE_EXPORT void *xxmalloc(size_t sz) {\
      return TheHeapWrapper::malloc(sz);\
    }\
    \
    ATTRIBUTE_EXPORT void xxfree(void *ptr) {\
      TheHeapWrapper::free(ptr);\
    }\
    \
    ATTRIBUTE_EXPORT void *xxmemalign(size_t alignment, size_t sz) {\
      return TheHeapWrapper::memalign(alignment, sz);\
    }\
    \
    ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void *ptr) {\
      return TheHeapWrapper::getSize(ptr);	\
    }\
    \
    ATTRIBUTE_EXPORT void xxmalloc_lock() {\
      TheHeapWrapper::xxmalloc_lock();\
    }\
    \
    ATTRIBUTE_EXPORT void xxmalloc_unlock() {\
      TheHeapWrapper::xxmalloc_unlock();\
    }\
  }

#endif
#endif
