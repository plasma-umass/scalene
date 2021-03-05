#pragma once

#ifndef NEXTHEAP_HPP
#define NEXTHEAP_HPP

#include <dlfcn.h>

#if defined(__APPLE__)

// XXX use the same code on __APPLE__?
class NextHeap {
 public:
  enum { Alignment = alignof(max_align_t) };

  inline void *malloc(size_t sz) { return ::malloc(sz); }
  inline void *memalign(size_t alignment, size_t size) {
    void *buf;
    ::posix_memalign(&buf, alignment, size);
    return buf;
  }
  inline bool free(void *ptr) {
    ::free(ptr);
    return true;
  }
  inline size_t getSize(void *ptr) { return ::malloc_size(ptr); }
};

#else

#include "staticbufferheap.hpp"

extern "C" {
  typedef void *mallocFn(size_t);
  typedef void freeFn(void *);
  typedef size_t mallocusablesizeFn(void *);
  typedef void *memalignFn(size_t, size_t);
}

/**
 * Provides access to the original system heap, even if the standard malloc/free/etc.
 * have been redirected by way of LD_PRELOAD, MacOS interpose, etc.
 */
class NextHeap {
 public:
  enum { Alignment = alignof(max_align_t) };

  inline void *malloc(size_t sz) {
    if (unlikely(_malloc == nullptr)) {
      if (_inInit) {
        return _initHeap->malloc(sz);
      }
      init(); // FIXME call through std::call_once (here and elsewhere)?
    }
    return (*_malloc)(sz);
  }

  inline void *memalign(size_t alignment, size_t sz) {
    if (unlikely(_memalign == nullptr)) {
      if (_inInit) {
        return _initHeap->malloc(sz);  // FIXME 'alignment' ignored
      }
      init();
    }
    return (*_memalign)(alignment, sz);
  }

  inline bool free(void *ptr) {
    if (unlikely(_free == nullptr)) {
      if (_inInit) {
        return false;
      }
      init();
    }
    if (!_initHeap->isValid(ptr)) {
      (*_free)(ptr);
    }
    return true;
  }

  inline size_t getSize(void *ptr) {
    if (unlikely(_malloc_usable_size == nullptr)) {
      if (_inInit) {
        return _initHeap->getSize(ptr);
      }
      init();
    }
    if (_initHeap->isValid(ptr)) {
      return _initHeap->getSize(ptr);
    }
    return (*_malloc_usable_size)(ptr);
  }

 private:
  void init() {
    // malloc et al can be called during initialization even before C++ constructors run,
    // so we rely on compile-time static data member initialization and on an in place new
    // to provide an interim heap in case what we call here needs it.
    if (_initHeap == 0) {
      _initHeap = new (_initHeapMem) StaticBufferHeap<INIT_HEAP_SIZE>;
      _inInit = true;

      _malloc_usable_size = (mallocusablesizeFn*) dlsym(RTLD_NEXT, "malloc_usable_size");
      _free = (freeFn*) dlsym(RTLD_NEXT, "free");
      _malloc = (mallocFn*) dlsym(RTLD_NEXT, "malloc");
      _memalign = (memalignFn*) dlsym(RTLD_NEXT, "memalign");

      _inInit = false;
    }
  }

  static const int INIT_HEAP_SIZE = 640 * 1024; // should be enough for anyone :)

  inline static char _initHeapMem[sizeof(StaticBufferHeap<INIT_HEAP_SIZE>)];
  inline static StaticBufferHeap<INIT_HEAP_SIZE>* _initHeap{0};
  inline static bool _inInit{false};
  inline static mallocFn *_malloc{0};
  inline static freeFn *_free{0};
  inline static memalignFn *_memalign{0};
  inline static mallocusablesizeFn *_malloc_usable_size{0};
};
#endif

#endif
