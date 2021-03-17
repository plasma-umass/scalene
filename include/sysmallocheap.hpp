#pragma once

#ifndef SYSMALLOCHEAP_HPP
#define SYSMALLOCHEAP_HPP

#include <dlfcn.h>

#if defined(__APPLE__)

// FIXME use the non-__APPLE__ code on __APPLE__ as well to reduce unnecessary variants?
class SysMallocHeap {
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

/**
 * Provides access to the original system heap, even if the standard malloc/free/...
 * have been redirected by way of LD_PRELOAD, MacOS interpose, etc.
 */
class SysMallocHeap {
  decltype(::malloc)* _malloc{0};
  decltype(::free)* _free{0};
  decltype(::memalign)* _memalign{0};
  decltype(::malloc_usable_size)* _malloc_usable_size{0};

 public:
  enum { Alignment = alignof(max_align_t) };

  SysMallocHeap() :
      _malloc((decltype(_malloc)) dlsym(RTLD_NEXT, "malloc")),
      _free((decltype(_free)) dlsym(RTLD_NEXT, "free")),
      _memalign((decltype(_memalign)) dlsym(RTLD_NEXT, "memalign")),
      _malloc_usable_size((decltype(_malloc_usable_size)) dlsym(RTLD_NEXT, "malloc_usable_size")) {}

  inline void *malloc(size_t sz) {
    return (*_malloc)(sz);
  }

  inline void *memalign(size_t alignment, size_t sz) {
    return (*_memalign)(alignment, sz);
  }

  inline void free(void *ptr) {
    (*_free)(ptr);
  }

  inline size_t getSize(void *ptr) {
    return (*_malloc_usable_size)(ptr);
  }
};
#endif

#endif
