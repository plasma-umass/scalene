#ifndef REPO_HPP
#define REPO_HPP

#include <assert.h>
#include <iostream>

#include "common.hpp"

template <unsigned long Size>
class RepoHeader {
private:

  enum { MAGIC_NUMBER = 0xCAFEBABE };
  
public:

  enum { Alignment = 2 * sizeof(unsigned long) };
  
  RepoHeader(unsigned long objectSize)
    : _allocated (0),
      _freed (0),
      //      _magic (MAGIC_NUMBER),
      _next (nullptr),
      _objectSize (objectSize),
      _numberOfObjects ((Size-sizeof(*this)) / objectSize)
  {
  }

  inline ATTRIBUTE_ALWAYS_INLINE auto getObjectSize() const {
    return _objectSize;
  }

  inline ATTRIBUTE_ALWAYS_INLINE auto getNumberOfObjects() const {
    return _numberOfObjects;
  }
  
  inline void setNext(RepoHeader * p) {
    _next = p;
  }

  inline auto getNext() const {
    return _next;
  }

  inline ATTRIBUTE_ALWAYS_INLINE auto getAllocated() const {
    return _allocated;
  }

  inline ATTRIBUTE_ALWAYS_INLINE void incAllocated() {
    _allocated++;
  }

  inline ATTRIBUTE_ALWAYS_INLINE auto getFreed() const {
    return _freed;
  }

  inline ATTRIBUTE_ALWAYS_INLINE void incFreed() {
    _freed++;
  }

  inline ATTRIBUTE_ALWAYS_INLINE bool isFull() const {
    return (_allocated == _numberOfObjects);
  }

  inline ATTRIBUTE_ALWAYS_INLINE bool isEmpty() const {
    return ((_freed == _numberOfObjects) || (_allocated == 0));
  }

  
private:
  
  const unsigned int _objectSize;
  unsigned int _numberOfObjects;
  unsigned int _allocated;  // total number of objects allocated so far.
  unsigned int _freed;      // total number of objects freed so far.
  RepoHeader * _next;

public:
  
  inline size_t getBaseSize() {
    assert(isValid());
    return _objectSize;
  }

  inline bool isValid() const {
    return true;
    //    return (_magic == MAGIC_NUMBER);
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

  inline Repo<Size> * getNext() const {
    return (Repo<Size> *) RepoHeader<Size>::getNext();
  }

  inline ATTRIBUTE_ALWAYS_INLINE constexpr auto getNumberOfObjects() const {
    return RepoHeader<Size>::getNumberOfObjects();
  }
  
  inline ATTRIBUTE_ALWAYS_INLINE void * malloc(size_t sz) {
    //    std::cout << "this = " << this << std::endl;
    assert(RepoHeader<Size>::isValid());
    assert (sz <= RepoHeader<Size>::getObjectSize());
    void * ptr;
    if (likely(!RepoHeader<Size>::isFull())) {
      ptr = &_buffer[RepoHeader<Size>::getAllocated() * RepoHeader<Size>::getObjectSize()];
      assert(inBounds(ptr));
      assert((uintptr_t) ptr % RepoHeader<Size>::Alignment == 0);
      RepoHeader<Size>::incAllocated();
    } else {
      ptr = nullptr;
    }
    return ptr;
  }

  inline ATTRIBUTE_ALWAYS_INLINE constexpr size_t getSize(void * ptr) {
    assert(RepoHeader<Size>::isValid());
    return RepoHeader<Size>::getBaseSize();
    //    return 0;
  }

  inline ATTRIBUTE_ALWAYS_INLINE constexpr bool inBounds(void * ptr) {
    assert(RepoHeader<Size>::isValid());
    char * cptr = reinterpret_cast<char *>(ptr);
    return ((cptr >= &_buffer[0]) && (cptr <= &_buffer[(getNumberOfObjects()-1) * RepoHeader<Size>::getObjectSize()]));
  }
  
  inline ATTRIBUTE_ALWAYS_INLINE void free(void * ptr) {
    assert(RepoHeader<Size>::isValid());
    assert(inBounds(ptr));
    RepoHeader<Size>::incFreed();
    assert(RepoHeader<Size>::getAllocated() <= getNumberOfObjects());
  }
    
protected:
  char _buffer[Size - sizeof(RepoHeader<Size>)];
};

#endif
