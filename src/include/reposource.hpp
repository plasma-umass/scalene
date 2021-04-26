#ifndef REPOSOURCE_HPP
#define REPOSOURCE_HPP

#include "common.hpp"
#include "repo.hpp"

template <int Size>
class RepoSource {
 private:
  enum { MAX_HEAP_SIZE = 3UL * 1024 * 1024 * 1024 };  // 3GB

  const char *_bufferStart;
  char *_buf;
  size_t _sz;

  constexpr auto align(void *ptr) {
    const auto alignedPtr = (void *)(((uintptr_t)ptr + Size - 1) & ~(Size - 1));
    return alignedPtr;
  }

 public:
  RepoSource()
      : _bufferStart(reinterpret_cast<char *>(MmapWrapper::map(MAX_HEAP_SIZE))),
        // Below, align the buffer and subtract the part removed by aligning it.
        _buf(reinterpret_cast<char *>(align((void *)_bufferStart))),
        _sz(MAX_HEAP_SIZE - ((uintptr_t)align((void *)_bufferStart) -
                             (uintptr_t)_bufferStart)) {
    for (auto i = 0; i < NUM_REPOS; i++) {
      _repos[i] = nullptr;
    }
    _emptyRepos = nullptr;
    static int counter = 0;
    counter++;
    // Sanity check.
    if (counter > 1) {
      abort();
    }
  }

  constexpr auto getHeapSize() { return MAX_HEAP_SIZE; }

  inline const char *getBufferStart() { return _bufferStart; }

  Repo<Size> *get(size_t sz) {
    std::lock_guard lock(_lock);
    //    tprintf::tprintf("repo: @,  (buf = @), @ get @\n", this, _buf, Size,
    //    sz);
    auto index = getIndex(sz);
    Repo<Size> *repo = nullptr;
    if (unlikely(getSource(index) == nullptr)) {
      // Nothing in this size. Check the empty list.
      if (_emptyRepos == nullptr) {
        // No empties. Allocate a new one.
        if (likely(sz < _sz)) {
          auto buf = _buf;
          _buf += Size;
          _sz -= Size;
          repo = new (buf) Repo<Size>(sz);
          assert(repo != nullptr);
          repo->setNext(nullptr);  // FIXME? presumably redundant.
          assert(repo->getState() == RepoHeader<Size>::RepoState::Unattached);
          return repo;
        } else {
          tprintf::tprintf("Scalene: Memory exhausted: sz = @\n", sz);
          return nullptr;
        }
      }
    }
    // If we get here, either there's a repo with the desired size or there's an
    // empty available.
    repo = getSource(index);
    if (!repo || (!repo->isEmpty() && _emptyRepos != nullptr)) {
      // Reformat an empty repo.
      assert(_emptyRepos->getState() ==
             RepoHeader<Size>::RepoState::RepoSource);
      repo = _emptyRepos;
      _emptyRepos = _emptyRepos->getNext();
      assert(repo->isEmpty());
      if (sz != repo->getObjectSize()) {
        //	tprintf::tprintf("reformatting empty (was @, now @)\n",
        // repo->getObjectSize(), sz);
        repo = new (repo) Repo<Size>(sz);
      } else {
        repo->setState(RepoHeader<Size>::RepoState::Unattached);
        repo->setNext(nullptr);
      }
      assert(repo->getObjectSize() == sz);
      return repo;
    }
    auto oldState = repo->setState(RepoHeader<Size>::RepoState::Unattached);
    // tprintf::tprintf("GET (@) popping @.\n", sz, repo);
    getSource(index) = getSource(index)->getNext();
    repo->setNext(nullptr);
    if (getSource(index) != nullptr) {
      assert(getSource(index)->isValid());
    }
    assert(repo->isValid());
    assert(repo->getNext() == nullptr);
    return repo;
  }

  void put(Repo<Size> *repo) {
    std::lock_guard lock(_lock);
    assert(repo != nullptr);
    assert(repo->isValid());
    if (repo->getState() == RepoHeader<Size>::RepoState::RepoSource) {
      // This should never happen.
      assert(0);
      // Fail gracefully.
      return;
    }
    auto oldState = repo->setState(RepoHeader<Size>::RepoState::RepoSource);
    assert(oldState != RepoHeader<Size>::RepoState::RepoSource);
    assert(repo->getNext() == nullptr);
    if (repo->isEmpty()) {
      // Put empty repos on the last array.
      repo->setNext(_emptyRepos);
      _emptyRepos = repo;
    } else {
      auto index = getIndex(repo->getObjectSize());
      repo->setNext(getSource(index));
      getSource(index) = repo;
    }
  }

 private:
  RepoSource(RepoSource &);
  RepoSource &operator=(const RepoSource &);

  // TBD: unify with RepoMan declarations.

  enum { MULTIPLE = 16 };
  enum { MAX_SIZE = 512 };
  enum { NUM_REPOS = Size / MULTIPLE };

  static ATTRIBUTE_ALWAYS_INLINE constexpr inline int getIndex(size_t sz) {
    return sz / MULTIPLE - 1;
  }

  HL::SpinLock _lock;
  Repo<Size> *_repos[NUM_REPOS];
  Repo<Size> *_emptyRepos;

  Repo<Size> *&getSource(int index) {
    assert(index >= 0);
    assert(index < NUM_REPOS);
    return _repos[index];
  }
};

#endif
