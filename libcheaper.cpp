// Size class calculator
// Dynamic arrays

#include <sys/mman.h>
#include <signal.h>

#include "tprintf.h"
#include "common.hpp"

class MmapArray {
public:
  static void * map(size_t sz) {
    //    std::lock_guard guard (_mutex);
    void * ptr = mmap((void *) 0,
		      sz,
		      PROT_READ | PROT_WRITE,
		      MAP_ANON | MAP_PRIVATE | MAP_NORESERVE,
		      -1,
		      0);
    if (ptr == MAP_FAILED) {
      return nullptr;
    }
    return ptr;
  }
  static void unmap(void * buf, size_t sz) {
    munmap(buf, sz);
  }
};

#include <cstring>
#include <iostream>
using namespace std;


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
    std::memcpy(newBuffer, _buffer, _length * sizeof(TYPE));
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


template <typename TYPE,
	  unsigned long Size>
class StaticStack {
public:
  StaticStack() : _index (0) {}
  auto getBuffer() { return _buf; }
  inline void push(const TYPE v) {
    _buf[_index] = v;
    _index++;
  }
  void fill() {
    _index = Size;
  }
  inline bool pop(TYPE& v) {
    if (_index > 0) {
      _index--;
      v = _buf[_index];
      return true;
    }
    return false;
  }
  inline auto size() const {
    return _index;
  }
  
private:
  unsigned long _index;
  TYPE _buf[Size];
};


template <typename TYPE,
	  unsigned long BatchSize = 8>
class Stack {
public:
  Stack() : _index (0) {}

  void mass_push(const TYPE v[BatchSize]) {
    memcpy(&_buf[_index], v, sizeof(TYPE) * BatchSize);
    _index += BatchSize;
  }
  
  void mass_pop(TYPE v[BatchSize]) {
    if (_index >= BatchSize) {
      _index -= BatchSize;
      memcpy(v, &_buf[_index], sizeof(TYPE) * BatchSize);
    } // Note: we fail silently if there are too few things on the stack.
  }
  
  inline void push(const TYPE v) {
    _buf[_index] = v;
    _index++;
  }

  inline auto size() const {
    return _index;
  }
  
  inline bool pop(TYPE& v) {
    if (likely(_index > 0)) {
      _index--;
      v = _buf[_index];
      return true;
    } else {
      return false;
    }
  }
  
private:
  unsigned long _index;
  DynArray<TYPE> _buf;
};



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


template <unsigned long Multiple = 8>
class ClassWarfare {
public:
  inline static void getSizeAndClass(const size_t sz, size_t& rounded, unsigned long& sizeClass) {
    rounded = (sz + (Multiple - 1)) & ~(Multiple - 1);
    sizeClass = rounded / Multiple - 1;
  }

  inline static void getSizeFromClass(const unsigned long sizeClass, size_t& sz) {
    sz = (sizeClass + 1) * Multiple;
  }
};

template <unsigned long NumClasses,
	  unsigned long Size = 1024UL * 1048576UL,
	  unsigned long Multiple = 8>
class BufferBump {
public:

  BufferBump() {
    for (auto i = 0; i < NumClasses; i++) {
      _bump[i] = (char *) _buf.getBuffer(i);
    }
  }
  
  __attribute__((noinline)) void * malloc(size_t sz) {
    size_t rounded;
    unsigned long sizeClass;
    ClassWarfare<Multiple>::getSizeAndClass(sz, rounded, sizeClass);
    auto ptr = _bump[sizeClass];
    _bump[sizeClass] += rounded;
    return reinterpret_cast<void *>(ptr);
  }

  inline size_t getSize(void * ptr) {
    size_t sz;
    auto cl = _buf.getClass(ptr);
#if 1
    if (unlikely((cl < 0) || (cl >= NumClasses))) {
      return 0;
    }
#endif
    ClassWarfare<Multiple>::getSizeFromClass(cl, sz);
    return sz;
  }
  
private:
  Buffer<NumClasses, Size> _buf;
  char * _bump[NumClasses];
};


template <unsigned long NumClasses,
	  unsigned long Size = 1024UL * 1048576UL,
	  unsigned long Multiple = 16,
	  unsigned long MinSize = 16>
class TheThang {
public:
  
  __attribute__((always_inline)) inline void * malloc(size_t sz) {
#if 1
    // TODO - slightly more sophisticated size class foo.
    // We should have a different set of size classes for larger sizes.
  
    if (unlikely(sz > NumClasses * Multiple)) {
      tprintf::tprintf("OH SHEET @\n", sz);
    }
#endif
    if (unlikely(sz < MinSize)) {
      sz = MinSize;
    }
    size_t rounded;
    unsigned long sizeClass;
    ClassWarfare<Multiple>::getSizeAndClass(sz, rounded, sizeClass);
    void * ptr;
    if (likely(_arr[sizeClass].pop(ptr))) {
      return ptr;
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
  
  BufferBump<NumClasses, Size, Multiple> _buf;
  Stack<void *> _arr[NumClasses];
};



template <class SuperHeap, unsigned long Bytes = 16 * 1048576>
class SampleHeap : public SuperHeap {
public:

  SampleHeap()
    : _timer (Bytes)
  {
    //    fprintf(stderr, "HELLO\n");
  }
  
  void * malloc(size_t sz) {
    if (sz >= _timer) {
      // Raise a signal.
      ////      raise(SIGVTALRM);
      tprintf::tprintf("freed memory = @\n", SuperHeap::freedMemory());
      // Reset the counter.
      _timer = Bytes;
    } else {
      _timer -= sz;
    }
    return SuperHeap::malloc(sz);
  }
  
private:
  long _timer;
};


static volatile bool initialized = false;
class Thang;
static Thang * theThang = nullptr;

class Thang : public SampleHeap<TheThang<400000, 128UL * 1048576UL>> {
public:
  Thang() {
    theThang = this;
    initialized = true;
  }
};

Thang& getThang() {
  static Thang thang;
  return thang;
}

extern "C" __attribute__((constructor)) void xxinit() {
  tprintf::tprintf("xxinit\n");
  theThang = &getThang();
}

extern "C" void * xxmalloc(size_t sz) {
  //  if (initialized) {
  //    return theThang->malloc(sz);
  // }
  return getThang().malloc(sz);
  // return theThang->malloc(sz);
}

extern "C" void xxfree(void * ptr) {
  theThang->free(ptr);
}

extern "C" void xxfree_sized(void * ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  theThang->free(ptr);
}

extern "C" size_t xxmalloc_usable_size(void * ptr) {
  return theThang->getSize(ptr); // TODO FIXME adjust for ptr offset?
}

extern "C" bool isMultiThreaded = true;

extern "C" void xxmalloc_lock() {
}

extern "C" void xxmalloc_unlock() {
}

#if 0
int main()
{
  TheThang<65536> thang;
  DynArray<unsigned long> arr;
  Stack<unsigned long> stk;
  for (int j = 0; j < 100000; j++) {
    void * buf[10000];
    for (int i = 0; i < 10000; i++) {
      //      buf[i] = thang.malloc(8);
      buf[i] = malloc(8);
    }
    for (int i = 0; i < 10000; i++) {
      // thang.free(buf[i]);
      free(buf[i]);
    }
  }
  
  cout << "DUDE." << endl;
  return 0;
}
#endif
