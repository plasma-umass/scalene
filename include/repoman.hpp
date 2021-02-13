#ifndef REPOMAN_HPP
#define REPOMAN_HPP

#include "common.hpp"
#include "repo.hpp"
//#include "reposource.hpp"
#include <assert.h>
#include <stdlib.h>

#include <iostream>
#include <new>

#include "heaplayers.h"

template <int Size, template <int> class Source>
class RepoMan {
 public:
  enum { Alignment = Repo<Size>::Alignment };

  RepoMan() {
    static_assert((Size & ~(Size - 1)) == Size, "Size must be a power of two.");
    static_assert(Size > MAX_SIZE, "Size must be larger than maximum size.");
    static_assert(NUM_REPOS >= 1, "Number of repos must be at least one.");
    // Initialize the repos for each size.
    for (auto index = 0; index < NUM_REPOS; index++) {
      _repos[index] = _repoSource.get((index + 1) * MULTIPLE);
      auto prevState =
          _repos[index]->setState(RepoHeader<Size>::RepoState::LocalRepoMan);
      assert(prevState == RepoHeader<Size>::RepoState::Unattached);
      assert(getIndex((index + 1) * MULTIPLE) == index);
      //      assert(_repos[index]->isEmpty());
    }
  }

  ~RepoMan() {
    for (auto index = 0; index < NUM_REPOS; index++) {
      if (_repos[index]->isEmpty()) {
        auto prevState =
            _repos[index]->setState(RepoHeader<Size>::RepoState::Unattached);
        assert(prevState == RepoHeader<Size>::RepoState::LocalRepoMan);
        _repoSource.put(_repos[index]);
      }
    }
  }

  // Check if this pointer came from us (inside the allocation buffer).
  inline ATTRIBUTE_ALWAYS_INLINE constexpr bool inBounds(void *ptr) {
    char *cptr = reinterpret_cast<char *>(ptr);
    auto in =
        ((cptr >= _repoSource.getBufferStart()) &&
         (cptr < (_repoSource.getBufferStart() + _repoSource.getHeapSize())));
    if (!in) {
      //      tprintf::tprintf("Out of bounds: @\n", ptr);
    }
    return in;
  }

  inline ATTRIBUTE_ALWAYS_INLINE void *malloc(size_t sz) {
    // Round sz up to next multiple of MULTIPLE.
    sz = roundUp(sz, MULTIPLE);
    // assert(sz >= MULTIPLE);
    void *ptr;
    if (likely(sz <= MAX_SIZE)) {
      //      tprintf::tprintf("repoman malloc @\n", sz);
      //      assert (sz == roundUp(sz, MULTIPLE));
      auto index = getIndex(sz);
      assert(_repos[index]->getObjectSize() == sz);
      assert(_repos[index]->getState() ==
             RepoHeader<Size>::RepoState::LocalRepoMan);
      ptr = _repos[index]->malloc(sz);
      if (likely(ptr != nullptr)) {
        assert((uintptr_t)ptr % Alignment == 0);
        return ptr;
      }
      while (ptr == nullptr) {
        static int iterations = 0;
        iterations++;
        ptr = _repos[index]->malloc(sz);
        if (ptr == nullptr) {
          _repos[index] = _repos[index]->getNext();
          if (_repos[index] == nullptr) {
            _repos[index] = _repoSource.get(sz);
            _repos[index]->setState(RepoHeader<Size>::RepoState::LocalRepoMan);
          }
          assert(_repos[index]->isValid());
        }
      }
    } else {
      ptr = allocateLarge(sz);
      //      tprintf::tprintf("LARGE: @\n", ptr);
    }
    assert((uintptr_t)ptr % Alignment == 0);
    return ptr;
  }

  inline ATTRIBUTE_ALWAYS_INLINE size_t free(void *ptr) {
    if (unlikely(!inBounds(ptr))) {
      if ((uintptr_t)ptr - (uintptr_t)getHeader(ptr) !=
          sizeof(RepoHeader<Size>)) {
        // Out of bounds.  Not one of our objects.
        // tprintf::tprintf("NOT ONE OF OUR OBJECTS: @\n", ptr);
        return 0;
      }
    }

    if (likely(ptr != nullptr)) {
      if (likely(getHeader(ptr)->isValid())) {
        auto sz = getSize(ptr);
        if (likely(sz <= MAX_SIZE)) {
          auto index = getIndex(sz);
          assert(_repos[index]->getObjectSize() == sz);
          auto r = reinterpret_cast<Repo<Size> *>(getHeader(ptr));
          assert(!r->isEmpty());
          if (unlikely(r->free(ptr))) {
            // If we just freed the whole repo and it's not our
            // current repo, give it back to the repo source for later
            // reuse.  (FOR NOW: put on the free list if it's not on
            // one already. We should impose a limit. TBD.)
            if (unlikely(r != _repos[index])) {
              if (r->getState() == RepoHeader<Size>::RepoState::Unattached) {
                r->setNext(_repos[index]);
                _repos[index] = r;
                r->setState(RepoHeader<Size>::RepoState::LocalRepoMan);
              }
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

  static ATTRIBUTE_ALWAYS_INLINE constexpr inline size_t roundUp(
      size_t sz, size_t multiple) {
    assert((multiple & (multiple - 1)) == 0);
    if (unlikely(sz < multiple)) {
      sz = multiple;
    }
    return (sz + multiple - 1) & ~(multiple - 1);
  }

  static ATTRIBUTE_ALWAYS_INLINE constexpr inline int getIndex(size_t sz) {
    return sz / MULTIPLE - 1;
  }

  static ATTRIBUTE_ALWAYS_INLINE constexpr inline RepoHeader<Size> *getHeader(
      void *ptr) {
    auto header = (RepoHeader<Size> *)((uintptr_t)ptr & ~(Size - 1));
    return header;
  }

  static ATTRIBUTE_ALWAYS_INLINE constexpr inline size_t getSize(void *ptr) {
    size_t sz = 0;
    auto headerPtr = getHeader(ptr);
    if (headerPtr->isValid()) {
      sz = headerPtr->getBaseSize();
    }
    ///    tprintf::tprintf("ptr = @, headerPtr = @, sz = @\n", ptr, headerPtr,
    ///    sz);
    return sz;
  }

  enum { MULTIPLE = 16 };

 private:
  constexpr auto align(void *ptr) {
    const auto alignedPtr = (void *)(((uintptr_t)ptr + Size - 1) & ~(Size - 1));
    return alignedPtr;
  }

  ATTRIBUTE_NEVER_INLINE void *allocateLarge(size_t sz) {
    // For now, allocate directly via mmap.
    // Add the space for the header metadata.
    auto origSize = sz;
    sz = sz + sizeof(RepoHeader<Size>);
    // Round sz up to next multiple of Size.
    sz = roundUp(sz, Size);
    // Ensure that this chunk of memory is appropriately aligned.

    void *alignedPtr = nullptr;

    if (sz <= Size) {
      // It's small enough: just use a repo.
      alignedPtr = _repoSource.get(origSize);

    } else {
      // Map until we find a suitably aligned chunk.
      // The goal here is to align the start of the next mmap request so it is
      // already suitably aligned.
      alignedPtr = MmapWrapper::map(sz);
      while ((uintptr_t)alignedPtr % Size != 0) {
        // Unmap one page at a time so we don't reuse it in a subsequent map
        // call.
        MmapWrapper::unmap((void *)((uintptr_t)alignedPtr + sz - 4096), 4096);
        alignedPtr = MmapWrapper::map(sz);
      }

#if 0
      // Complicated alignment logic, currently disabled.
      const auto totalRequest = 2 * sz;
      const auto originalPtr = MmapWrapper::map(totalRequest);
      const auto alignedPtr = (void *) (((uintptr_t) originalPtr + Size - 1) & ~(Size - 1));

      auto leftSize = 0;
      auto rightSize = 0;
    
      // Unmap the left part.
      if (originalPtr != alignedPtr) {
	tprintf::tprintf("UNMAPPING LEFT.\n");
	tprintf::tprintf("original = @, aligned = @\n", originalPtr, alignedPtr);
	leftSize = (uintptr_t) alignedPtr - (uintptr_t) originalPtr;
	MmapWrapper::unmap(originalPtr, leftSize);
      }
      // Unmap the right part.
      rightSize = totalRequest - (leftSize + sz);
      if (rightSize > 0) {
	const auto end = ((void *) ((uintptr_t) alignedPtr + sz));
	tprintf::tprintf("UNMAPPING RIGHT.\n");
	tprintf::tprintf("end = @, size = @\n", end, rightSize);
	MmapWrapper::unmap(end, rightSize);
      }
#endif
    }

    assert(align(alignedPtr) == alignedPtr);  // Verify alignment.
    auto bigObjBase = new (alignedPtr) RepoHeader<Size>(origSize);
    auto ptr = bigObjBase + 1;
    return ptr;
  }

  ATTRIBUTE_NEVER_INLINE void freeLarge(void *ptr, size_t sz) {
    // "Large" object handling.
    auto basePtr = reinterpret_cast<RepoHeader<Size> *>(ptr) - 1;
    if (align(basePtr) != basePtr) {
      // Not aligned = not one of our objects.
      return;
    }
    assert(align(basePtr) == basePtr);
    auto origSize = sz;
    sz = sz + sizeof(RepoHeader<Size>);
    // Round sz up to next multiple of Size.
    sz = roundUp(sz, Size);
    if (sz <= Size) {
      // It was actually a repo. Put it back.
      //      tprintf::tprintf("returning repo @ of size @\n", basePtr,
      //      origSize);
      _repoSource.put(reinterpret_cast<Repo<Size> *>(basePtr));
    } else {
      // Unmap it.
      MmapWrapper::unmap(basePtr, sz);
    }
  }

  enum { MAX_SIZE = 512 };
  enum { NUM_REPOS = MAX_SIZE / MULTIPLE };
  Repo<Size> *_repos[NUM_REPOS];
  Source<Size> _repoSource;
};

#endif
