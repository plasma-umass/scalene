#pragma once

#ifndef STATICBUFFERHEAP_H
#define STATICBUFFERHEAP_H

template <int BufferSize>
class StaticBufferHeap {
 public:
  StaticBufferHeap() {}

  enum { Alignment = alignof(std::max_align_t) };

  void *malloc(size_t sz) {
    auto oldAllocated = allocated();
    auto prevPtr = _bufPtr;
    if (sz == 0) {
      sz = Alignment;
    }
    sz = sz + (Alignment - (sz % Alignment));
    if (allocated() + sizeof(Header) + sz > BufferSize) {
      return nullptr;
    }
    _bufPtr += sz + sizeof(Header);
    new (prevPtr) Header(sz);
    auto ptr = (Header *)prevPtr + 1;
    assert(sz <= getSize(ptr));
    assert(isValid(ptr));
    assert(allocated() == oldAllocated + sz + sizeof(Header));
#if 0
    tprintf::tprintf("allocated @ sz = @\n",
		     sz,
		     (void *) ptr);
#endif
    return ptr;
  }

  void free(void *) {}

  size_t getSize(void *ptr) {
    if (isValid(ptr)) {
      auto sz = ((Header *)ptr - 1)->size;
      //      tprintf::tprintf("size of @ = @\n", ptr, sz);
      return sz;
    } else {
      return 0;
    }
  }

  bool isValid(void *ptr) {
    if ((uintptr_t)ptr >= (uintptr_t)_buf) {
      if ((uintptr_t)ptr < (uintptr_t)_buf + BufferSize) {
        return true;
      }
    }
    return false;
  }

 private:
  class Header {
   public:
    Header(size_t sz) : size(sz) {}
    alignas(Alignment) size_t size;
  };

  size_t allocated() { return (uintptr_t)_bufPtr - (uintptr_t)_buf; }

  alignas(Alignment) char _buf[BufferSize];
  char *_bufPtr{_buf};
};

#endif
