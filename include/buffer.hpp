#ifndef BUFFER_H
#define BUFFER_H

#include "mmaparray.hpp"

template <unsigned long NumClasses,
	  unsigned long Size = 1024UL * 1048576UL>
class Buffer {
public:
  Buffer()
  {
    _buf = (char *) MmapArray::map((NumClasses + 1) * Size);
    _originalBuf = _buf;
    // Round up.
    _buf = (char *) (((uintptr_t) _buf + Size - 1) & ~(Size-1));
  }

  ~Buffer()
  {
    MmapArray::unmap(_originalBuf, Size);
  }

  void * getBuffer(int i) {
    auto ptr = &_buf[i * Size];
    return ptr;
  }

  long getClass(void * ptr) {
    return ((uintptr_t) ptr - (uintptr_t) _buf) / Size;
  }
  
private:
  
  char * _buf;
  char * _originalBuf;
};


#endif
