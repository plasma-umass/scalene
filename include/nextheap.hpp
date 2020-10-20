#pragma once

#ifndef NEXTHEAP_HPP
#define NEXTHEAP_HPP

#include <dlfcn.h>

#if defined(__APPLE__)

class NextHeap {
public:
  enum { Alignment = alignof(max_align_t) };
  
  inline void * malloc(size_t sz) {
    return ::malloc(sz);
  }
  inline bool free(void * ptr) {
    ::free(ptr);
    return true;
  }
  inline size_t getSize(void * ptr) {
    return ::malloc_size(ptr);
  }
};

#else

extern "C" {
  typedef void * mallocFn(size_t);
  typedef void freeFn(void *);
  typedef size_t mallocusablesizeFn(void *);
}

class NextHeap {
private:
public:
  enum { Alignment = alignof(max_align_t) };
  NextHeap()
    : _inMalloc (false),
      _inFree (false),
      _malloc (nullptr),
      _free (nullptr),
      _malloc_usable_size (nullptr)
  {
  }
  inline void * malloc(size_t sz) {
    if (unlikely(_malloc == nullptr)) {
      return slowPathMalloc(sz);
    }
    return (*_malloc)(sz);
  }
  inline bool free(void * ptr) {
    if (unlikely(_free == nullptr)) {
      return slowPathFree(ptr);
    }
    (*_free)(ptr);
    return true;
  }

  inline size_t getSize(void * ptr) {
    if (unlikely(!_malloc_usable_size)) {
      if (_inMalloc) {
	// If we're in a recursive call, return 0 for the size.
	return 0;
      }
      _inMalloc = true;
      *(void **)(&_malloc_usable_size) = dlsym(RTLD_NEXT, "malloc_usable_size");
      _inMalloc = false;
    }
    return (*_malloc_usable_size)(ptr);
  }
  
private:

  bool slowPathFree(void * ptr) {
    if (_inFree) {
      return false;
    }
    _inFree = true;
    *(void **)(&_free) = dlsym(RTLD_NEXT, "free");
    _inFree = false;
    (*_free)(ptr);
    return true;
  }
  
  void * slowPathMalloc(size_t sz) {
    if (_inMalloc) {
      // If we're in a recursive call, return null.
      return 0;
    }
    _inMalloc = true;
    // Welcome to the hideous incantation required to use dlsym with C++...
    *(void **)(&_malloc) = dlsym(RTLD_NEXT, "malloc");
    _inMalloc = false;
    return (*_malloc)(sz);
  }
  
  bool _inMalloc;
  bool _inFree;
  mallocFn * _malloc;
  freeFn * _free;
  mallocusablesizeFn * _malloc_usable_size;
};
#endif

#endif
