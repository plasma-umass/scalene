#pragma once

#ifndef NEXTHEAP_HPP
#define NEXTHEAP_HPP

#include <dlfcn.h>

#if defined(__APPLE__)

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

class NextHeap {
private:
  StaticBufferHeap<640 * 1024> buffer; // should be enough for anyone :)

public:
  enum { Alignment = alignof(max_align_t) };
  NextHeap()
      : _inMalloc(false), _inMemalign(false), _inFree(false), _malloc(nullptr),
        _free(nullptr), _memalign(nullptr), _malloc_usable_size(nullptr) {}
  inline void *malloc(size_t sz) {
    if (unlikely(_malloc == nullptr)) {
      if (_inMalloc) {
        return buffer.malloc(sz);
      }
      init();
    }
    return (*_malloc)(sz);
  }
  inline void *memalign(size_t alignment, size_t sz) {
    if (unlikely(_memalign == nullptr)) {
      if (_inMalloc) {
        return buffer.malloc(sz); // FIXME
      }
      init();
    }
    return (*_memalign)(alignment, sz);
  }
  inline bool free(void *ptr) {
    if (unlikely(_free == nullptr)) {
      if (_inMalloc) {
        return false;
      }
      init();
    }
    if (!buffer.isValid(ptr)) {
      (*_free)(ptr);
    }
    return true;
  }

  inline size_t getSize(void *ptr) {
    if (unlikely(_malloc_usable_size == nullptr)) {
      if (_inMalloc) {
        return buffer.getSize(ptr);
      }
      init();
    }
    if (buffer.isValid(ptr)) {
      return buffer.getSize(ptr);
    }
    return (*_malloc_usable_size)(ptr);
  }

private:
  void init() {
    _inMalloc = true;
    // Welcome to the hideous incantation required to use dlsym with C++...
    *(void **)(&_malloc_usable_size) = dlsym(RTLD_NEXT, "malloc_usable_size");
    *(void **)(&_free) = dlsym(RTLD_NEXT, "free");
    *(void **)(&_malloc) = dlsym(RTLD_NEXT, "malloc");
    *(void **)(&_memalign) = dlsym(RTLD_NEXT, "memalign");
    _inMalloc = false;
  }

  bool slowPathFree(void *ptr) {
    (*_free)(ptr);
    return true;
  }

  void *slowPathMalloc(size_t sz) { return (*_malloc)(sz); }

  void *slowPathMemalign(size_t alignment, size_t sz) {
    return (*_memalign)(alignment, sz);
  }

  bool _inMalloc;
  bool _inMemalign;
  bool _inFree;
  mallocFn *_malloc;
  freeFn *_free;
  memalignFn *_memalign;
  mallocusablesizeFn *_malloc_usable_size;
};
#endif

#endif
