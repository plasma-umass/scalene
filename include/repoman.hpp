#ifndef REPOMAN_HPP
#define REPOMAN_HPP

#include "common.hpp"
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
  enum { MAX_HEAP_SIZE = 1 * 1024 * 1024 * 1024 }; // 1GB
  char * _bufferStart;
  
public:

  enum { Alignment = Repo<Size>::Alignment };
  
  RepoMan()
    : _bufferStart (reinterpret_cast<char *>(MmapWrapper::map(MAX_HEAP_SIZE))),
      _repoSource(_bufferStart, MAX_HEAP_SIZE)
  {
    static_assert((Size & ~(Size-1)) == Size, "Size must be a power of two.");
    // Initialize the repos for each size.
    for (auto index = 0; index < NUM_REPOS; index++) {
      _repos[index] = _repoSource.get((index + 1) * MULTIPLE);
      assert(getIndex((index + 1) * MULTIPLE) == index);
      assert(_repos[index]->isEmpty());
    }
  }

  inline ATTRIBUTE_ALWAYS_INLINE constexpr bool inBounds(void * ptr) const {
    char * cptr = reinterpret_cast<char *>(ptr);
    return ((cptr >= _bufferStart) && (cptr < (_bufferStart + MAX_HEAP_SIZE)));
  }
    
  inline ATTRIBUTE_ALWAYS_INLINE void * malloc(size_t sz) {
    //    tprintf::tprintf("malloc @\n", sz);
    if (unlikely(sz == 0)) { sz = MULTIPLE; }
    // assert(sz >= MULTIPLE);
    void * ptr;
    if (likely(sz <= MAX_SIZE)) {
      // Round sz up to next multiple of MULTIPLE.
      sz = roundUp(sz, MULTIPLE);
      //      assert (sz == roundUp(sz, MULTIPLE));
      auto index = getIndex(sz);
      ptr = nullptr;
      while (ptr == nullptr) {
	ptr = _repos[index]->malloc(sz);
	if (ptr == nullptr) {
	  //	  tprintf::tprintf("exhausted @\n", _repos[index]);
	  assert(_repos[index]->isFull());
	  _repoSourceLock.lock();
	  _repos[index] = _repoSource.get(sz);
	  assert((_repos[index] == nullptr) || _repos[index]->isEmpty());
	  _repoSourceLock.unlock();
	}
      }
    } else {
      ptr = allocateLarge(sz);
    }
    assert((uintptr_t) ptr % Alignment == 0);
    //    tprintf::tprintf("malloc @ = @\n", sz, ptr);
    return ptr;
  }

  inline ATTRIBUTE_ALWAYS_INLINE size_t free(void * ptr) {
    if (unlikely(!inBounds(ptr))) {
      if ((uintptr_t) ptr - (uintptr_t) getHeader(ptr) != sizeof(RepoHeader<Size>)) {
	//	tprintf::tprintf("out of bounds!\n");
	return 0;
      }
    }
    //    tprintf::tprintf("free @\n", ptr);
    if (likely(ptr != nullptr)) {
      if (likely(getHeader(ptr)->isValid())) {
	//      std::cout << "checking " << ptr << std::endl;
	auto sz = getSize(ptr);
	//	tprintf::tprintf("free sz = @\n", sz);
	if (likely(sz <= MAX_SIZE)) {
	  auto index = getIndex(sz);
	  auto r = reinterpret_cast<Repo<Size> *>(getHeader(ptr));
	  // assert(!r->isEmpty());
	  r->free(ptr);
	  // If we just freed the whole repo and it's not our current repo, give it back to the repo source for later reuse.
	  if ((r != _repos[index]) && (unlikely(r->isEmpty()))) {
	    _repoSourceLock.lock();
	    _repoSource.put(r);
	    _repoSourceLock.unlock();
	  } else {
	    if (unlikely(r->isEmpty())) {
	      new (r) Repo<Size>(sz);
	    }
	  }
	} else {
	  freeLarge(ptr, sz);
	}
	return sz;
      }
    }
    return 0;
  }

  static ATTRIBUTE_ALWAYS_INLINE constexpr inline size_t roundUp(size_t sz, size_t multiple) {
    assert((multiple & (multiple - 1)) == 0);
    if (unlikely(sz < multiple)) {
      sz = multiple;
    }
    return (sz + multiple - 1) & ~(multiple - 1);
  }
  
  static ATTRIBUTE_ALWAYS_INLINE constexpr inline int getIndex(size_t sz) {
    return sz / MULTIPLE - 1;
  }
  
  static ATTRIBUTE_ALWAYS_INLINE constexpr inline RepoHeader<Size> * getHeader(void * ptr) {
    auto header = (RepoHeader<Size> *) ((uintptr_t) ptr & ~(Size-1));
    return header;
  }
  
  static ATTRIBUTE_ALWAYS_INLINE constexpr inline size_t getSize(void * ptr) {
    size_t sz = 0;
    auto headerPtr = getHeader(ptr);
    if (headerPtr->isValid()) {
      sz = headerPtr->getBaseSize();
    }
    return sz;
  }

  enum { MULTIPLE = 16 };
  
private:

  ATTRIBUTE_NEVER_INLINE void * allocateLarge(size_t sz) {
    // For now, allocate directly via mmap.
    // Add the space for the header metadata.
    auto origSize = sz;
    sz = sz + sizeof(RepoHeader<Size>);
    // Round sz up to next multiple of Size.
    sz = roundUp(sz, Size);
    //      std::cout << "allocating object of size " << sz << std::endl;
    // FIXME force alignment!
    //      tprintf::tprintf("*****big object orig = @, sz = @\n", origSize, sz);
    
    auto basePtr = MmapWrapper::map(sz);
    assert((uintptr_t) basePtr % Size == 0); // verify alignment
    auto bigObjBase = new (basePtr) RepoHeader<Size>(origSize);
    auto ptr = bigObjBase + 1; // reinterpret_cast<char *>(basePtr) + sizeof(RepoHeader);
    //      std::cout << "object size = " << getSize(ptr) << ", ptr = " << ptr << std::endl;
    return ptr;
  }

  ATTRIBUTE_NEVER_INLINE void freeLarge(void * ptr, size_t sz) {
    // "Large" object handling.
    auto basePtr = reinterpret_cast<RepoHeader<Size> *>(ptr) - 1;
    auto origSize = sz;
    sz = sz + sizeof(RepoHeader<Size>);
    // Round sz up to next multiple of Size.
    sz = roundUp(sz, Size);
    //	  tprintf::tprintf("FREE @ (@)\n", ptr, sz);
    MmapWrapper::unmap(basePtr, sz);
  }
  
  enum { MAX_SIZE = 512 };
  enum { NUM_REPOS = MAX_SIZE / MULTIPLE };
  Repo<Size> * _repos[NUM_REPOS];
  RepoSource<Size> _repoSource;
  HL::SpinLock _repoSourceLock;
};

#endif
