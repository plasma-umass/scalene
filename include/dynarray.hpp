#ifndef DYNARRAY_H
#define DYNARRAY_H

#include "mmaparray.hpp"

template <typename TYPE>
class DynArray {
public:

  DynArray()
  {
    const auto minSize = 4096;
    _length = minSize / sizeof(TYPE);
    _buffer = reinterpret_cast<TYPE*>(MmapArray::map(minSize));
  }
  
  inline TYPE& operator[](int index) {
    if (likely(index < _length)) {
      // Common case.
      return _buffer[index];
    } else {
      return slowPath(index);
    }
  }
  
private:

  TYPE& slowPath(int index) {
    // Grow by doubling until big enough to reach index.
    auto newLength = _length;
    while (newLength <= index) {
      newLength *= 2;
    }
    // Copy out the old buffer into the new one.
    auto newBuffer = reinterpret_cast<TYPE*>(MmapArray::map(newLength * sizeof(TYPE)));
    memcpy(newBuffer, _buffer, _length * sizeof(TYPE));
    // Dump the old one.
    MmapArray::unmap(_buffer, _length);
    // Replace with the new buffer and length.
    _buffer = newBuffer;
    _length = newLength;
    return _buffer[index];
  }
  
  TYPE * _buffer;
  unsigned long _length;
};

#endif
