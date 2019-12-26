#ifndef CHEAPHEAP_H
#define CHEAPHEAP_H

#include "bufferbump.hpp"
#include "stack.hpp"
#include "classwarfare.hpp"
#include "tprintf.h"

template <unsigned long NumClasses,
	  unsigned long Size = 1024UL * 1048576UL,
	  unsigned long Multiple = 8,
	  unsigned long MinSize = 16>
class CheapHeap {
public:
  
  __attribute__((always_inline)) inline void * malloc(size_t sz) {
#if 1
    // TODO - slightly more sophisticated size class foo.
    // We should have a different set of size classes for larger sizes.
  
    if (unlikely(sz > NumClasses * Multiple)) {
      tprintf::tprintf("OH SHEET @\n", sz);
    }
    if (unlikely(sz < MinSize)) {
      sz = MinSize;
    }
#endif
    size_t rounded;
    unsigned long sizeClass;
    ClassWarfare<Multiple>::getSizeAndClass(sz, rounded, sizeClass);
    {
      void * ptr;
      if (likely(_arr[sizeClass].pop(ptr))) {
	return ptr;
      }
    }
    return slowPathMalloc(rounded);
  }
  
  __attribute__((always_inline)) inline void free(void * ptr) {
    if (unlikely(ptr == nullptr)) {
      return;
    }
    auto sz = _buf.getSize(ptr);
    if (unlikely(sz == 0)) { // check for out of bounds.
      return;
    }
    size_t rounded;
    unsigned long sizeClass;
    ClassWarfare<Multiple>::getSizeAndClass(sz, rounded, sizeClass);
    _arr[sizeClass].push(ptr);
  }

  size_t freedMemory() {
    size_t totalFreed = 0;
    for (auto i = 0; i < NumClasses; i++) {
      size_t sz;
      ClassWarfare<Multiple>::getSizeFromClass(i, sz);
      totalFreed += _arr[i].size() * sz;
    }
    return totalFreed;
  }
  
  inline size_t getSize(void * ptr) {
    return _buf.getSize(ptr);
  }
  
private:

  __attribute__((noinline)) void * slowPathMalloc(size_t rounded) {
    return _buf.malloc(rounded);
  }
  
  Stack<void *> _arr[NumClasses];
  BufferBump<NumClasses, Size, Multiple> _buf;
};

#endif
