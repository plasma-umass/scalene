#ifndef REPOMAN_HPP
#define REPOMAN_HPP

#include "repo.hpp"
#include "reposource.hpp"
#include "heaplayers.h"

#include <new>
#include <iostream>
#include <stdlib.h>


template <int Size>
class RepoMan {
public:

  // FIXME static assert that Size is a power of two.
  
  RepoMan()
  {
    // Initialize the repos for each size.
    for (auto index = 0; index < NUM_REPOS; index++) {
      repoPointers[index] = _repoSource.get((index + 1) * MULTIPLE);
      assert(repoPointers[index]->isEmpty());
    }
  }

  void * malloc(size_t sz) {
    //    tprintf::tprintf("malloc @\n", sz);
    if (sz < MULTIPLE) { sz = MULTIPLE; }
    void * ptr;
    if (sz <= MAX_SIZE) {
      // Round sz up to next multiple of MULTIPLE.
      sz = (sz + MULTIPLE - 1) & ~(MULTIPLE - 1);
      //      tprintf::tprintf("size now = @\n", sz);
      int index = sz / MULTIPLE - 1;
      //    std::cout << "repos[index] = " << &repos[index] << std::endl;
      ptr = nullptr;
      while (ptr == nullptr) {
	ptr = repoPointers[index]->malloc(sz);
	if (ptr == nullptr) {
	  repoPointers[index] = _repoSource.get(sz);
	}
      }
    } else {
      // For now, allocate directly via mmap.
      // Add the space for the header metadata.
      auto origSize = sz;
      sz = sz + sizeof(RepoHeader);
      // Round sz up to next multiple of Size.
      sz = (sz + Size - 1) & ~(Size - 1);
      //      std::cout << "allocating object of size " << sz << std::endl;
      // FIXME force alignment!
      tprintf::tprintf("*****big object sz = @\n", sz);
      auto basePtr = MmapWrapper::map(sz);
      auto bigObjBase = new (basePtr) RepoHeader(origSize);
      ptr = bigObjBase + 1; // reinterpret_cast<char *>(basePtr) + sizeof(RepoHeader);
      //      std::cout << "object size = " << getSize(ptr) << ", ptr = " << ptr << std::endl;
    }
    //    tprintf::tprintf("malloc @ = @\n", sz, ptr);
    return ptr;
  }
  
  void free(void * ptr) {
    //    tprintf::tprintf("free @\n", ptr);
    if (ptr != nullptr) {
      if (getHeader(ptr)->isValid()) {
	//      std::cout << "checking " << ptr << std::endl;
	auto sz = getSize(ptr);
	if (sz <= MAX_SIZE) {
	  int index = sz / MULTIPLE - 1;
	  Repo<Size> * r = reinterpret_cast<Repo<Size> *>(getHeader(ptr));
	  r->free(ptr);
	  // If we just freed the whole repo, give it back to the repo source for later reuse.
	  if (r->isEmpty()) {
	    _repoSource.put(r);
	  }
	} else {
	  // "Large" object handling.
	  auto basePtr = reinterpret_cast<RepoHeader *>(ptr) - 1;
	  MmapWrapper::unmap(basePtr, sz);
	}
      }
    }
  }

  static constexpr inline RepoHeader * getHeader(void * ptr) {
    //    tprintf::tprintf("getHeader @\n", ptr);
    auto header = (RepoHeader *) ((uintptr_t) ptr & ~(Size-1));
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
  Repo<Size> * repoPointers[NUM_REPOS];
  RepoSource<Size> _repoSource;
};

#endif
