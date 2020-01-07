#ifndef REPO_HPP
#define REPO_HPP

#include <assert.h>
#include <iostream>


// Used just to account for the size of vtable pointers.
//class Vtable {
//public:
//  virtual void run() = 0;
//};

class RepoHeader {
public:
  RepoHeader(unsigned long objectSize)
    : _objectSize (objectSize),
      _allocated (0)
  {}
  unsigned long _objectSize;
  unsigned long _allocated;  // total number of objects allocated so far.

  // Below must be virtual to force the instantiation of a vtable pointer.
  virtual size_t getBaseSize() {
    //    std::cout << "getBaseSize: this = " << this << std::endl;
    return _objectSize;
  }
};

// The base for all object sizes of repos.
template <unsigned long Size>
class RepoBase : public RepoHeader {
protected:
  RepoBase(unsigned long objectSize)
    : RepoHeader(objectSize)
  {}
public:
  virtual size_t getSize(void *) = 0;
  virtual void * malloc(size_t) = 0;
  virtual void free(void *) = 0;
  virtual bool isFull() = 0;
  virtual bool isEmpty() = 0;
  
protected:
  char _buffer[Size - sizeof(RepoHeader)];
};


// A repo for a specific object size.
template <unsigned long ObjectSize, unsigned long Size>
class Repo : public RepoBase<Size> {
public:
  enum { NumObjects = (Size - sizeof(RepoHeader)) / ObjectSize };
  
private:

  class Object {
  public:
    char buf[ObjectSize];
  };

public:
  
  Repo() : RepoBase<Size>(ObjectSize)
  {
  }

  inline bool isFull() {
    return (RepoHeader::_allocated == NumObjects);
  }

  inline bool isEmpty() {
    return (RepoHeader::_allocated == 0);
  }

  inline void * malloc(size_t sz) {
    //    std::cout << "this = " << this << std::endl;
    assert (sz <= ObjectSize);
    if (RepoHeader::_allocated < NumObjects) {
      auto object = reinterpret_cast<Object *>(RepoBase<Size>::_buffer);
      auto * ptr = &object[RepoHeader::_allocated];
      assert(inBounds(ptr));
      RepoHeader::_allocated++;
      return ptr;
    } else {
      //      std::cout << "out of objects: _allocated = " << RepoHeader::_allocated << std::endl;
      return nullptr;
    }
  }

  inline constexpr size_t getSize(void * ptr) {
    return RepoHeader::getBaseSize();
    auto objPtr = reinterpret_cast<Object *>(ptr);
    if (inBounds(objPtr)) {
      return RepoBase<Size>::getBaseSize();
    }
    return 0;
  }

  inline constexpr bool inBounds(void * ptr) {
    auto objPtr = reinterpret_cast<Object *>(ptr);
    auto object = reinterpret_cast<Object *>(RepoBase<Size>::_buffer);
    return ((objPtr >= &object[0]) && (objPtr <= &object[NumObjects-1]));
  }
  
  inline void free(void * ptr) {
    assert(inBounds(ptr));
    RepoHeader::_allocated--;
    assert(RepoHeader::_allocated <= NumObjects);
  }
    
};

#endif
