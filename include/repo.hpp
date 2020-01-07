#ifndef REPO_HPP
#define REPO_HPP

#include <assert.h>
#include <iostream>


// Used just to account for the size of vtable pointers.
//class Vtable {
//public:
//  virtual void run() = 0;
//};

template <unsigned long Size>
class RepoHeader {
private:

  enum { MAGIC_NUMBER = 0xCAFEBABE };
  
public:

  enum { Alignment = 2 * sizeof(unsigned long) };
  
  RepoHeader(unsigned long objectSize)
    : _allocated (0),
      _freed (0),
      _magic (MAGIC_NUMBER),
      _next (nullptr)
  {
    setObjectSize(objectSize);
  }

  inline void setObjectSize(size_t sz) {
    _objectSize = sz;
    _numberOfObjects = ((Size-sizeof(*this)) / _objectSize);
    //    tprintf::tprintf("setting object size to @, numObjects = @\n", sz, _numberOfObjects);
  }

  inline auto getObjectSize() const {
    return _objectSize;
  }

  inline auto getNumberOfObjects() const {
    return _numberOfObjects;
  }
  
  inline void setNext(RepoHeader * p) {
    _next = p;
  }

  inline auto getNext() const {
    return _next;
  }

  inline auto getAllocated() const {
    return _allocated;
  }

  inline void incAllocated() {
    _allocated++;
  }

  inline auto getFreed() const {
    return _freed;
  }

  inline void incFreed() {
    _freed++;
  }

  inline bool isFull() {
    return (_allocated  == getNumberOfObjects());
  }

  inline bool isEmpty() {
    return ((_freed == getNumberOfObjects()) || (_allocated == 0));
  }

  
private:
  unsigned long _objectSize;
  unsigned long _numberOfObjects;
  unsigned long _allocated;  // total number of objects allocated so far.
  unsigned long _freed;      // total number of objects freed so far.
  const unsigned long _magic;
  RepoHeader * _next;

public:
  
  inline size_t getBaseSize() {
    assert(isValid());
    return _objectSize;
  }

  inline bool isValid() const {
    // return true;
    return (_magic == MAGIC_NUMBER);
  }
  
};

// The base for all object sizes of repos.
template <unsigned long Size>
class Repo : public RepoHeader<Size> {
public:
  
  Repo(unsigned long objectSize)
    : RepoHeader<Size>(objectSize)
  {
    static_assert(sizeof(*this) == Size, "Something has gone terribly wrong.");
  }

  inline constexpr auto getNumberOfObjects() const {
    return RepoHeader<Size>::getNumberOfObjects();
  }
  
  inline void * malloc(size_t sz) {
    //    std::cout << "this = " << this << std::endl;
    assert(RepoHeader<Size>::isValid());
    assert (sz <= RepoHeader<Size>::getObjectSize());
    if (sz < RepoHeader<Size>::getObjectSize()) {
      tprintf::tprintf("OK WAT @ should be @\n", sz, RepoHeader<Size>::getObjectSize());
    }
    void * ptr;
    if (!RepoHeader<Size>::isFull()) {
      ptr = &_buffer[RepoHeader<Size>::getAllocated() * RepoHeader<Size>::getObjectSize()];
      assert(inBounds(ptr));
      assert((uintptr_t) ptr % RepoHeader<Size>::Alignment == 0);
      RepoHeader<Size>::incAllocated();
    } else {
      //      std::cout << "out of objects: _allocated = " << RepoHeader<Size>::_allocated << std::endl;
      ptr = nullptr;
    }
    //    tprintf::tprintf("malloc @ = @\n", sz, ptr);
    return ptr;
  }

  inline constexpr size_t getSize(void * ptr) {
    assert(RepoHeader<Size>::isValid());
    return RepoHeader<Size>::getBaseSize();
    //    return 0;
  }

  inline constexpr bool inBounds(void * ptr) {
    assert(RepoHeader<Size>::isValid());
    char * cptr = reinterpret_cast<char *>(ptr);
    return ((cptr >= &_buffer[0]) && (cptr <= &_buffer[(getNumberOfObjects()-1) * RepoHeader<Size>::getObjectSize()]));
  }
  
  inline void free(void * ptr) {
    assert(RepoHeader<Size>::isValid());
    assert(inBounds(ptr));
    RepoHeader<Size>::incFreed();
    assert(RepoHeader<Size>::getAllocated() <= getNumberOfObjects());
  }
    
protected:
  char _buffer[Size - sizeof(RepoHeader<Size>)];
};

#endif
