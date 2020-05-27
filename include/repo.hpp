#ifndef REPO_HPP
#define REPO_HPP

#include <assert.h>
#include <iostream>

#include "libdivide.h"
#include "common.hpp"

template <unsigned long Size>
class RepoHeader {
private:

  enum { MAGIC_NUMBER = 0xCAFEBABE };

public:

  enum { Alignment = 2 * sizeof(unsigned long) };
  
  RepoHeader(unsigned long objectSize)
    : _bumped (0),
      _freed (0),
      _magic (MAGIC_NUMBER),
      _nextRepo (nullptr),
      _nextObject (nullptr),
      _objectSize (objectSize),
      _divider (objectSize),
      _numberOfObjects ((Size-sizeof(*this)) / objectSize)
  {
    static_assert(sizeof(RepoHeader) % 16 == 0, "Misaligned.");
  }

  inline ATTRIBUTE_ALWAYS_INLINE auto getObjectSize() const {
    return _objectSize;
  }

  inline ATTRIBUTE_ALWAYS_INLINE auto getNumberOfObjects() const {
    return _numberOfObjects;
  }
  
  inline void setNext(RepoHeader * p) {
    _nextRepo = p;
  }

  inline auto getNext() const {
    return _nextRepo;
  }

  inline ATTRIBUTE_ALWAYS_INLINE auto getFreed() const {
    return _freed;
  }

  inline ATTRIBUTE_ALWAYS_INLINE constexpr bool inBounds(void * ptr, void * buf) {
    assert(RepoHeader<Size>::isValid());
    char * cbuf = reinterpret_cast<char *>(buf);
    char * cptr = reinterpret_cast<char *>(ptr);
    return ((cptr >= &cbuf[0]) && (cptr <= &cbuf[(getNumberOfObjects()-1) * getObjectSize()]));
  }
  
  inline ATTRIBUTE_ALWAYS_INLINE void * malloc(size_t sz) {
    assert(RepoHeader<Size>::isValid());
    assert(sz == getBaseSize());
    Object * obj = nullptr;
    auto * cBuf = reinterpret_cast<char *>(this + 1);
    assert(_bumped <= _numberOfObjects);
    if (_bumped == _numberOfObjects) {
#if 0
      obj = nullptr;
#else
      obj = _nextObject;
      if (obj != nullptr) {
	assert(inBounds(obj, cBuf));
	_nextObject = obj->getNext();
	_freed--;
      }
#endif
    } else {
      assert(_bumped < _numberOfObjects);
      obj = (Object *) &cBuf[_bumped * sz];
      _bumped++;
    }
    assert((obj == nullptr) || inBounds(obj, cBuf));
    if (obj != nullptr) {
      assert(((uintptr_t) obj - (uintptr_t) (this + 1)) % sz == 0);
    }
    return obj;
  }
  
  // Increment the number of freed objects (invoked by free).
  // Returns true iff this free resulted in the whole repo being free.
  inline ATTRIBUTE_ALWAYS_INLINE bool free(void * ptr) { // incFreed() {
    if (ptr == nullptr) { return false; }
    
    // Pointer must be in buffer bounds; guaranteed by caller.

    // Align pointer.
#if 1
    auto offset = fast_modulo((uintptr_t) ptr - (uintptr_t) (this + 1));
#else
    // slow (ordinary) modulo operator, replaced by call to libdivide above.
    auto sz = getBaseSize();
    auto offset = ((uintptr_t) ptr - (uintptr_t) (this + 1)) % sz;
#endif
    ptr = reinterpret_cast<void *> ((uintptr_t) ptr - offset);
    
    assert(_freed < _numberOfObjects);
    // Note: a double free could create a cycle.
    // Thread this object onto the freelist.
    _freed++;
    if (unlikely(_freed == _numberOfObjects)) {
      clear();
      return true;
    } else {
    assert(sizeof(Object) <= getBaseSize());
      auto obj = new (ptr) Object;
      obj->setNext(_nextObject);
      _nextObject = obj;
      return false;
    }
  }

  inline ATTRIBUTE_ALWAYS_INLINE bool isEmpty() const {
    return ((_freed == _numberOfObjects) || (_bumped == 0));
  }

  
private:
  
  void clear() {
    _bumped = 0;
    _freed = 0;
    _nextObject = nullptr;
  }

  class Object {
  public:
    Object()
      : _magic (0xDEADBEEF),
	_next (nullptr)
    {}
    Object * getNext() const { assert(isValid()); return _next; }
    void setNext(Object * o) { assert(isValid()); _next = o; }
  private:
    bool isValid() const { return _magic == 0xDEADBEEF; }
    Object * _next;
    unsigned long _magic;
  };
  
  const uint32_t _objectSize;
  const libdivide::divider<uint32_t> _divider;
  uint32_t _numberOfObjects;
  uint32_t _bumped;     // total number of objects allocated so far via pointer-bumping.
  uint32_t _freed;      // total number of objects freed so far.
  uint32_t _magic;
  RepoHeader * _nextRepo;
  Object * _nextObject;

public:

  inline uint32_t fast_modulo(uint32_t v) {
    auto quotient = v / _divider;
    return v - (quotient * _objectSize);
  }
 
  inline size_t getBaseSize() {
    assert(isValid());
    return _objectSize;
  }

  inline bool isValid() const {
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
    assert((uintptr_t) _buffer - (uintptr_t) this == sizeof(RepoHeader<Size>));

  }

  inline Repo<Size> * getNext() const {
    return (Repo<Size> *) RepoHeader<Size>::getNext();
  }

  inline ATTRIBUTE_ALWAYS_INLINE constexpr auto getNumberOfObjects() const {
    return RepoHeader<Size>::getNumberOfObjects();
  }
  
  inline ATTRIBUTE_ALWAYS_INLINE void * malloc(size_t sz) {
    assert(RepoHeader<Size>::isValid());
    assert (sz == RepoHeader<Size>::getObjectSize());
    auto ptr = RepoHeader<Size>::malloc(sz);
    if (ptr != nullptr) {
      assert(inBounds(ptr));
      assert((uintptr_t) ptr % RepoHeader<Size>::Alignment == 0);
    }
    return ptr;
  }

  inline ATTRIBUTE_ALWAYS_INLINE constexpr size_t getSize(void * ptr) {
    if (RepoHeader<Size>::isValid()) {
      return RepoHeader<Size>::getBaseSize();
    } else {
      return 0;
    }
  }

  // Returns true iff this free caused the repo to become empty (and thus available for reuse for another size).
  inline ATTRIBUTE_ALWAYS_INLINE bool free(void * ptr) {
    assert(RepoHeader<Size>::isValid());
    assert(inBounds(ptr));
    return RepoHeader<Size>::free(ptr);
  }
    
private:
  
  char _buffer[Size - sizeof(RepoHeader<Size>)];

  inline ATTRIBUTE_ALWAYS_INLINE constexpr bool inBounds(void * ptr) {
    return RepoHeader<Size>::inBounds(ptr, _buffer);
  }

};

#endif
