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
  
  enum { MAX_HEAP_SIZE = 3UL * 1024 * 1024 * 1024 }; // 3GB
  char * _bufferStart;
  
public:

  enum { Alignment = Repo<Size>::Alignment };
  
  RepoMan()
    : _bufferStart (reinterpret_cast<char *>(MmapWrapper::map(MAX_HEAP_SIZE))),
      _repoSource(_bufferStart, MAX_HEAP_SIZE)
  {
    static_assert((Size & ~(Size-1)) == Size, "Size must be a power of two.");
    static_assert(Size > MAX_SIZE, "Size must be larger than maximum size.");
    // Initialize the repos for each size.
    for (auto index = 0; index < NUM_REPOS; index++) {
      _repos[index] = _repoSource.get((index + 1) * MULTIPLE);
      assert(getIndex((index + 1) * MULTIPLE) == index);
      assert(_repos[index]->isEmpty());
    }
  }

  // Check if this pointer came from us (inside the allocation buffer).
  inline ATTRIBUTE_ALWAYS_INLINE constexpr bool inBounds(void * ptr) const {
    char * cptr = reinterpret_cast<char *>(ptr);
    return ((cptr >= _bufferStart) && (cptr < (_bufferStart + MAX_HEAP_SIZE)));
  }
    
  inline ATTRIBUTE_ALWAYS_INLINE void * malloc(size_t sz) {
    // Round sz up to next multiple of MULTIPLE.
    sz = roundUp(sz, MULTIPLE);
    // assert(sz >= MULTIPLE);
    void * ptr;
    if (likely(sz <= MAX_SIZE)) {
      //      assert (sz == roundUp(sz, MULTIPLE));
      auto index = getIndex(sz);
      ptr = _repos[index]->malloc(sz);
      if (likely(ptr != nullptr)) {
	assert((uintptr_t) ptr % Alignment == 0);
	return ptr;
      }
      while (ptr == nullptr) {
	ptr = _repos[index]->malloc(sz);
	if (ptr == nullptr) {
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
    return ptr;
  }

  inline ATTRIBUTE_ALWAYS_INLINE size_t free(void * ptr) {
    if (unlikely(!inBounds(ptr))) {
      if ((uintptr_t) ptr - (uintptr_t) getHeader(ptr) != sizeof(RepoHeader<Size>)) {
	// Out of bounds.  Not one of our objects.
	return 0;
      }
    }

    if (likely(ptr != nullptr)) {
      if (likely(getHeader(ptr)->isValid())) {
	auto sz = getSize(ptr);
	if (likely(sz <= MAX_SIZE)) {
	  auto index = getIndex(sz);
	  auto r = reinterpret_cast<Repo<Size> *>(getHeader(ptr));
	  assert(!r->isEmpty());
	  if (unlikely(r->free(ptr))) {
	    assert(r->isEmpty());
	    // If we just freed the whole repo and it's not our current repo, give it back to the repo source for later reuse.
	    if (unlikely(r != _repos[index])) {
	      _repoSourceLock.lock();
	      _repoSource.put(r);
	      _repoSourceLock.unlock();
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
    // FIXME force alignment!
    //    tprintf::tprintf("mapping object of size @\n", sz);
    auto basePtr = MmapWrapper::map(sz);
    // assert((uintptr_t) basePtr % Size == 0); // verify alignment
    auto bigObjBase = new (basePtr) RepoHeader<Size>(origSize);
    auto ptr = bigObjBase + 1; // reinterpret_cast<char *>(basePtr) + sizeof(RepoHeader);
    return ptr;
  }

  ATTRIBUTE_NEVER_INLINE void freeLarge(void * ptr, size_t sz) {
    // "Large" object handling.
    auto basePtr = reinterpret_cast<RepoHeader<Size> *>(ptr) - 1;
    auto origSize = sz;
    sz = sz + sizeof(RepoHeader<Size>);
    // Round sz up to next multiple of Size.
    sz = roundUp(sz, Size);
    //    tprintf::tprintf("freeLarge: sz = @\n", sz);
    MmapWrapper::unmap(basePtr, sz);
  }
  
  enum { MAX_SIZE = 512 };
  enum { NUM_REPOS = MAX_SIZE / MULTIPLE };
  Repo<Size> * _repos[NUM_REPOS];
  RepoSource<Size> _repoSource;
  HL::SpinLock _repoSourceLock;
};

#endif
