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
private:

  enum { MAGIC_NUMBER = 0xCAFEBABE };
  
public:
  RepoHeader(unsigned long objectSize)
    : _objectSize (objectSize),
      _allocated (0),
      _magic (MAGIC_NUMBER),
      _next (nullptr)
  {}
  unsigned long _objectSize;
  unsigned long _magic;
  unsigned long _allocated;  // total number of objects allocated so far.
  RepoHeader * _next;
  
  size_t getBaseSize() {
    assert(isValid());
    return _objectSize;
  }

  bool isValid() const {
    return (_magic == MAGIC_NUMBER);
  }
  
};

// The base for all object sizes of repos.
template <unsigned long Size>
class Repo : public RepoHeader {
public:
  
  Repo(unsigned long objectSize)
    : RepoHeader(objectSize)
  {}

  inline constexpr auto getNumberOfObjects() const {
    return (Size - sizeof(RepoHeader)) / _objectSize;
  }
  
  inline bool isFull() {
    return (RepoHeader::_allocated == getNumberOfObjects());
  }

  inline bool isEmpty() {
    return (RepoHeader::_allocated == 0);
  }

  inline void * malloc(size_t sz) {
    //    std::cout << "this = " << this << std::endl;
    assert(RepoHeader::isValid());
    assert (sz <= RepoHeader::_objectSize);
    if (!isFull()) {
      auto * ptr = &_buffer[RepoHeader::_allocated * RepoHeader::_objectSize];
      assert(inBounds(ptr));
      RepoHeader::_allocated++;
      return ptr;
    } else {
      //      std::cout << "out of objects: _allocated = " << RepoHeader::_allocated << std::endl;
      return nullptr;
    }
  }

  inline constexpr size_t getSize(void * ptr) {
    assert(RepoHeader::isValid());
    return RepoHeader::getBaseSize();
    if (inBounds(ptr)) {
      return getBaseSize();
    }
    return 0;
  }

  inline constexpr bool inBounds(void * ptr) {
    assert(RepoHeader::isValid());
    char * cptr = reinterpret_cast<char *>(ptr);
    return ((cptr >= &_buffer[0]) && (cptr <= &_buffer[(getNumberOfObjects()-1) * RepoHeader::_objectSize]));
  }
  
  inline void free(void * ptr) {
    assert(RepoHeader::isValid());
    assert(inBounds(ptr));
    assert(RepoHeader::_allocated > 0);
    RepoHeader::_allocated--;
    assert(RepoHeader::_allocated <= getNumberOfObjects());
  }
    
protected:
  char _buffer[Size - sizeof(RepoHeader)];
};


#if 0
// A repo for a specific object size.
template <unsigned long ObjectSize, unsigned long Size>
//template <unsigned long Size>
class RepoX : public RepoBase<Size> {
public:
  enum { NumObjects = (Size - sizeof(RepoHeader)) / ObjectSize };
  
private:

  class Object {
  public:
    char buf[ObjectSize];
  };

public:
  
  RepoX() : RepoBase<Size>(ObjectSize)
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

#endif
