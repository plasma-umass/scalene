#ifndef REPOSOURCE_HPP
#define REPOSOURCE_HPP

#include "common.hpp"
#include "repo.hpp"

template <int Size>
class RepoSource {
private:
  
  enum { MAX_HEAP_SIZE = 3UL * 1024 * 1024 * 1024 }; // 3GB

  const char * _bufferStart;
  char * _buf;
  size_t _sz;

  constexpr auto align (void * ptr) {
    const auto alignedPtr = (void *) (((uintptr_t) ptr + Size - 1) & ~(Size - 1));
    return alignedPtr;
  }
  
public:

  RepoSource()
    : _bufferStart (reinterpret_cast<char *>(MmapWrapper::map(MAX_HEAP_SIZE))),
      // Below, align the buffer and subtract the part removed by aligning it.
      _buf(reinterpret_cast<char *>(align((void *) _bufferStart))),
      _sz (MAX_HEAP_SIZE - ((uintptr_t) align((void *) _bufferStart) - (uintptr_t) _bufferStart))
  {
    static int counter = 0;
    counter++;
    // Sanity check.
    if (counter > 1) {
      abort();
    }
  }

  constexpr auto getHeapSize() {
    return MAX_HEAP_SIZE;
  }
  
  inline const char * getBufferStart() {
    return _bufferStart;
  }
  
  inline bool isValid() const {
#if defined(NDEBUG)
    return true;
#endif
    return true;
  }
  
  Repo<Size> * get(size_t sz) {
    // tprintf::tprintf("repo: @,  (buf = @), @ get @\n", this, _buf, Size, sz);
    assert(isValid());
    auto index = getIndex(sz);
    Repo<Size> * repo = nullptr;
    if (unlikely(getSource(index) == nullptr)) {
      // Allocate a new one. FIXME ensure alignment.
      if (likely(sz < _sz)) {
	auto buf = _buf;
	_buf += Size;
	_sz -= Size;
	// tprintf::tprintf("buf now = @, _sz now = @\n", _buf, _sz);
	//      auto buf = MmapWrapper::map(Size);
	// Must ensure sz is a proper size.
	//assert(sz % Alignment == 0);
	repo = new (buf) Repo<Size>(sz);
	// tprintf::tprintf("GET (@) mmapping: @.\n", sz, repo);
	assert(repo != nullptr);
	repo->setNext(nullptr); // FIXME? presumably redundant.
	assert (repo->getState() == RepoHeader<Size>::RepoState::Unattached);
	assert(isValid());
	return repo;
      } else {
	tprintf::tprintf("Scalene: Memory exhausted: sz = @\n", sz);
	assert(isValid());
	return nullptr;
      }
    } else {
      repo = getSource(index);
      auto oldState = repo->setState(RepoHeader<Size>::RepoState::Unattached);
      assert (oldState == RepoHeader<Size>::RepoState::RepoSource);
      // tprintf::tprintf("GET (@) popping @.\n", sz, repo);
      getSource(index) = getSource(index)->getNext();
      repo->setNext(nullptr);
      // new (repo) Repo<Size>(sz);
      if (getSource(index) != nullptr) {
	assert(getSource(index)->isValid());
      }
    }
    assert(repo->isValid());
    // tprintf::tprintf("reposource: @ - GET @ = @ [empty = @]\n", this, sz, repo, repo->isEmpty());
    assert(isValid());
    assert(repo->getNext() == nullptr);
    return repo;
  }

  void put(Repo<Size> * repo) {
    assert(isValid());
    assert(repo != nullptr);
    assert(repo->isValid());
    if (repo->getState() == RepoHeader<Size>::RepoState::RepoSource) {
      tprintf::tprintf("THIS IS BAD. repo = @\n", repo);
      abort();
    }
    auto oldState = repo->setState(RepoHeader<Size>::RepoState::RepoSource);
    assert(oldState != RepoHeader<Size>::RepoState::RepoSource);
    assert(repo->getNext() == nullptr);
    auto index = getIndex(repo->getSize(nullptr));
    repo->setNext(getSource(index));
    getSource(index) = repo;
    assert(isValid());
    // tprintf::tprintf("reposource: @ - PUT @ (sz = @) [empty = @]\n", this, repo, repo->getObjectSize(), repo->isEmpty());
  }
  
private:

  RepoSource(RepoSource&);
  RepoSource& operator=(const RepoSource&);
  
  // TBD: unify with RepoMan declarations.
  
  enum { MULTIPLE = 16 };
  enum { MAX_SIZE = 512 };
  enum { NUM_REPOS = MAX_SIZE / MULTIPLE };
  
  static ATTRIBUTE_ALWAYS_INLINE constexpr inline int getIndex(size_t sz) {
    return sz / MULTIPLE - 1;
  }
  
  static Repo<Size> *& getSource(int index) {
    static Repo<Size> * repos[NUM_REPOS] { nullptr }; // TBD: add one to the end for empty repos.
    return repos[index];
  }
  
};

#endif
