#pragma once

#ifndef HEAPREDIRECT_H
#define HEAPREDIRECT_H

#include "staticbufferheap.hpp"

/**
 * Redirects the system heap calls to a custom heap, using Heap-Layers'
 * wrappers.
 *
 * In order to service ::malloc through a custom heap, the custom heap's
 * constructor and its malloc method need to run; if either one of these,
 * directly or indirectly, need to call ::malloc, that would lead to an infinite
 * recursion.  To avoid this, we detect such recursive ::malloc calls using a
 * thread-local boolean variable and service them from a statically allocated
 * heap.
 *
 * The thread-local variable's and the static heap's initialization must be done
 * carefully so as not to require ::malloc when no heap is available to service
 * it from. To further complicate things, ::malloc is/can be invoked early
 * during executable startup, before C++ constructors for global objects.  On
 * MacOS, this seems to happen before thread initialization: attempts to use
 * thread_local or __thread lead to an abort() in _tlv_bootstrap.
 *
 * To work around the C++ constructor issue, we use static initializers within
 * functions; for the thread_local/__thread issue, we use POSIX thread-local
 * data.  We prefer __atomic calls to std::atomic because STL code feels more
 * likely to invoke malloc. We use std::recursive_mutex and std::lock_guard to
 * avoid introducing more code and because they don't seem to require malloc,
 * but may need to move to pthread_mutex if that should change.
 *
 * The problem is really that "won't use malloc" AFAIK isn't part of most of
 * these primitives' contracts, so we stand on shaky ground.
 *
 * @author Juan Altmayer Pizzorno
 */
template <typename CustomHeapType, int STATIC_HEAP_SIZE>
class HeapWrapper {
  static pthread_key_t *getKey() {
    // C++14 version of "inline static" data member
    static pthread_key_t _inMallocKey;
    return &_inMallocKey;
  }

  static bool isInMalloc() {
    // modified double-checked locking pattern
    // (https://en.wikipedia.org/wiki/Double-checked_locking)
    static enum {
      NEEDS_KEY = 0,
      CREATING_KEY = 1,
      DONE = 2
    } inMallocKeyState{NEEDS_KEY};
    static std::recursive_mutex m;

    auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_ACQUIRE);
    if (state != DONE) {
      std::lock_guard<decltype(m)> g{m};

      state = __atomic_load_n(&inMallocKeyState, __ATOMIC_RELAXED);
      if (unlikely(state == CREATING_KEY)) {
        return true;
      } else if (unlikely(state == NEEDS_KEY)) {
        __atomic_store_n(&inMallocKeyState, CREATING_KEY, __ATOMIC_RELAXED);
        if (pthread_key_create(getKey(), 0) !=
            0) {  // may call malloc/calloc/...
          abort();
        }
        __atomic_store_n(&inMallocKeyState, DONE, __ATOMIC_RELEASE);
      }
    }

    return pthread_getspecific(*getKey()) != 0;
  }

  static void setInMalloc(bool state) {
    pthread_setspecific(*getKey(), state ? (void *)1 : 0);
  }

  typedef LockedHeap<std::mutex, StaticBufferHeap<STATIC_HEAP_SIZE>>
      StaticHeapType;

  static StaticHeapType &getTheStaticHeap() {
    static StaticHeapType theStaticHeap;
    return theStaticHeap;
  }

  static CustomHeapType &getTheCustomHeap() {
    static CustomHeapType thang;
    return thang;
  }

 public:
  static void *xxmalloc(size_t sz) {
    if (unlikely(isInMalloc())) {
      return getTheStaticHeap().malloc(sz);
    }

    setInMalloc(true);
    void *ptr = getTheCustomHeap().malloc(sz);
    setInMalloc(false);
    return ptr;
  }

  static void *xxmemalign(size_t alignment, size_t sz) {
    if (unlikely(isInMalloc())) {
      return getTheStaticHeap().memalign(alignment, sz);
    }

    setInMalloc(true);
    void *ptr = getTheCustomHeap().memalign(alignment, sz);
    setInMalloc(false);
    return ptr;
  }

  static void xxfree(void *ptr) {
    if (likely(!getTheStaticHeap().isValid(ptr))) {
      getTheCustomHeap().free(ptr);
    }
  }

  static size_t xxmalloc_usable_size(void *ptr) {
    if (unlikely(getTheStaticHeap().isValid(ptr))) {
      return getTheStaticHeap().getSize(ptr);
    }

    return getTheCustomHeap().getSize(ptr);
  }

  static void xxmalloc_lock() { getTheCustomHeap().lock(); }

  static void xxmalloc_unlock() { getTheCustomHeap().unlock(); }
};

#define HEAP_REDIRECT(CustomHeap, staticSize)                                  \
  typedef HeapWrapper<CustomHeap, staticSize> Wrapper;                         \
  extern "C" {                                                                 \
  ATTRIBUTE_EXPORT void *xxmalloc(size_t sz) { return Wrapper::xxmalloc(sz); } \
                                                                               \
  ATTRIBUTE_EXPORT void xxfree(void *ptr) { Wrapper::xxfree(ptr); }            \
                                                                               \
  ATTRIBUTE_EXPORT void *xxmemalign(size_t alignment, size_t sz) {             \
    return Wrapper::xxmemalign(alignment, sz);                                 \
  }                                                                            \
                                                                               \
  ATTRIBUTE_EXPORT size_t xxmalloc_usable_size(void *ptr) {                    \
    return Wrapper::xxmalloc_usable_size(ptr);                                 \
  }                                                                            \
                                                                               \
  ATTRIBUTE_EXPORT void xxmalloc_lock() { Wrapper::xxmalloc_lock(); }          \
                                                                               \
  ATTRIBUTE_EXPORT void xxmalloc_unlock() { Wrapper::xxmalloc_unlock(); }      \
  }

#endif
