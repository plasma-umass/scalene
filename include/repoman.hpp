#ifndef REPOMAN_HPP
#define REPOMAN_HPP

#include "repo.hpp"
#include "reposource.hpp"
#include "heaplayers.h"

#include <assert.h>
#include <new>
#include <iostream>
#include <stdlib.h>


template <int Size>
class RepoMan {
private:
  enum { MAX_HEAP_SIZE = 1024 * 1024 * 1024 };
  char * _bufferStart;
  
public:

  // FIXME static assert that Size is a power of two.
  
  RepoMan()
    : _bufferStart (reinterpret_cast<char *>(MmapWrapper::map(MAX_HEAP_SIZE))),
      _repoSource(_bufferStart, MAX_HEAP_SIZE)
  {
    // Initialize the repos for each size.
    for (auto index = 0; index < NUM_REPOS; index++) {
      _repoPointers[index] = _repoSource.get((index + 1) * MULTIPLE);
      assert(getIndex((index + 1) * MULTIPLE) == index);
      assert(_repoPointers[index]->isEmpty());
    }
  }

  inline bool inBounds(void * ptr) const {
    char * cptr = reinterpret_cast<char *>(ptr);
    return ((cptr >= _bufferStart) && (cptr < (_bufferStart + MAX_HEAP_SIZE)));
  }
    
  void * malloc(size_t sz) {
    //    tprintf::tprintf("malloc @\n", sz);
    if (sz < MULTIPLE) { sz = MULTIPLE; }
    void * ptr;
    if (sz <= MAX_SIZE) {
      // Round sz up to next multiple of MULTIPLE.
      sz = roundUp(sz, MULTIPLE);
      //      tprintf::tprintf("size now = @\n", sz);
      auto index = getIndex(sz);
      //    std::cout << "repos[index] = " << &repos[index] << std::endl;
      ptr = nullptr;
      while (ptr == nullptr) {
	ptr = _repoPointers[index]->malloc(sz);
	if (ptr == nullptr) {
	  assert(_repoPointers[index]->isFull());
	  _repoPointers[index] = _repoSource.get(sz);
	  assert(_repoPointers[index]->isEmpty());
	}
      }
    } else {
      // For now, allocate directly via mmap.
      // Add the space for the header metadata.
      auto origSize = sz;
      sz = sz + sizeof(RepoHeader<Size>);
      // Round sz up to next multiple of Size.
      sz = roundUp(sz, Size);
      //      std::cout << "allocating object of size " << sz << std::endl;
      // FIXME force alignment!
      tprintf::tprintf("*****big object orig = @, sz = @\n", origSize, sz);

      // FIXME! This is no good. Leaks memory.
      auto basePtr = MmapWrapper::map(sz);
      auto bigObjBase = new (basePtr) RepoHeader<Size>(origSize);
      ptr = bigObjBase + 1; // reinterpret_cast<char *>(basePtr) + sizeof(RepoHeader);
      //      std::cout << "object size = " << getSize(ptr) << ", ptr = " << ptr << std::endl;
    }
    //    tprintf::tprintf("malloc @ = @\n", sz, ptr);
    return ptr;
  }
  
  void free(void * ptr) {
    if (!inBounds(ptr)) {
      return;
    }
    //    tprintf::tprintf("free @\n", ptr);
    if (ptr != nullptr) {
      if (getHeader(ptr)->isValid()) {
	//      std::cout << "checking " << ptr << std::endl;
	auto sz = getSize(ptr);
	if (sz <= MAX_SIZE) {
	  auto index = getIndex(sz);
	  auto r = reinterpret_cast<Repo<Size> *>(getHeader(ptr));
	  assert(!r->isEmpty());
	  r->free(ptr);
	  // If we just freed the whole repo, give it back to the repo source for later reuse.
	  if (r->isEmpty()) {
	    _repoSource.put(r);
	    if (_repoPointers[index] == r) {
	      _repoPointers[index] = _repoSource.get(sz);
	    }
	  }
	} else {
	  // "Large" object handling.
	  auto basePtr = reinterpret_cast<RepoHeader<Size> *>(ptr) - 1;
	  MmapWrapper::unmap(basePtr, sz);
	}
      }
    }
  }

  static constexpr inline size_t roundUp(size_t sz, size_t multiple) {
    assert((multiple & (multiple - 1)) == 0);
    return (sz + multiple - 1) & ~(multiple - 1);
  }
  
  static constexpr inline int getIndex(size_t sz) {
    return sz / MULTIPLE - 1;
  }
  
  static constexpr inline RepoHeader<Size> * getHeader(void * ptr) {
    //    tprintf::tprintf("getHeader @\n", ptr);
    auto header = (RepoHeader<Size> *) ((uintptr_t) ptr & ~(Size-1));
    return header;
  }
  
  static constexpr inline size_t getSize(void * ptr) {
    size_t sz = 0;
    auto headerPtr = getHeader(ptr);
    if (headerPtr->isValid()) {
      //    std::cout << "headerPtr = " << (void *) headerPtr << ", ptr = " << ptr << std::endl;
      sz = headerPtr->getBaseSize();
    }
    //    tprintf::tprintf("getSize @ = @\n", ptr, sz);
    return sz;
  }
  
private:

  enum { MULTIPLE = 8 };
  enum { MAX_SIZE = 512 };
  enum { NUM_REPOS = MAX_SIZE / MULTIPLE };
  //  Repo<Size> * repos;
  Repo<Size> * _repoPointers[NUM_REPOS];
  RepoSource<Size> _repoSource;
};

#endif
