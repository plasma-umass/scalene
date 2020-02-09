#ifndef REPOSOURCE_HPP
#define REPOSOURCE_HPP

#include "common.hpp"
#include "repo.hpp"

template <int Size>
class RepoSource {
private:

  char * _buf;
  size_t _sz;
  int _totalAvailable;
  
public:

  RepoSource(char * buf, size_t sz)
    : _buf (buf),
      _sz (sz),
      _totalAvailable (0)
  {}

  inline bool isValid() const {
#if defined(NDEBUG)
    return true;
#endif
#if 1 // turn off expensive integrity checks for now.
    return true;
#else
    int count = 0;
    Repo<Size> * repo = getSource();
    while (repo != nullptr) {
      count++;
      repo = repo->getNext();
      if (count > _totalAvailable + 100000) {
	tprintf::tprintf("LOOKS LIKE A LOOP.\n");
	abort();
      }
    }
    if (count != _totalAvailable) {
      tprintf::tprintf("count = @, totalAvailable = @\n", count, _totalAvailable);
    }
    return (count == _totalAvailable);
#endif
  }
  
  Repo<Size> * get(size_t sz) {
    assert(isValid());
    Repo<Size> * repo = nullptr;
    if (unlikely(getSource() == nullptr)) {
      assert(_totalAvailable == 0);
      // Allocate a new one. FIXME ensure alignment.
      if (likely(sz < _sz)) {
	//	tprintf::tprintf("GET (@) mmapping.\n", sz);
	auto buf = _buf;
	_buf += Size;
	_sz -= Size;
	//      auto buf = MmapWrapper::map(Size);
	// Must ensure sz is a proper size.
	assert(sz % Alignment == 0);
	repo = new (buf) Repo<Size>(sz);
	assert(repo != nullptr);
	repo->setNext(nullptr); // FIXME? presumably redundant.
	assert(isValid());
	return repo;
      } else {
	tprintf::tprintf("Scalene: Memory exhausted: sz = @\n", sz);
	assert(isValid());
	return nullptr;
      }
    } else {
      //      tprintf::tprintf("GET (@) popping.\n", sz);
      assert(_totalAvailable > 0);
      repo = getSource();
      getSource() = getSource()->getNext();
      new (repo) Repo<Size>(sz);
      if (getSource() != nullptr) {
	assert(getSource()->isValid());
	assert(getSource()->isEmpty());
      }
      _totalAvailable--;
    }
    assert(repo->isValid());
    assert(repo->isEmpty());
    //    tprintf::tprintf("GET @ = @ [total available = @]\n", sz, repo, _totalAvailable);
    assert(isValid());
    return repo;
  }

  void put(Repo<Size> * repo) {
    assert(isValid());
    assert(repo != nullptr);
    Repo<Size> * r = getSource();
    assert(repo->isValid());
    assert(repo->isEmpty());
    //    assert(getSource() == nullptr || getSource()->isEmpty());
    repo->setNext(getSource());
    getSource() = repo;
    _totalAvailable++;
    assert(isValid());
    //    tprintf::tprintf("PUT @ (sz = @) [total available = @]\n", repo, repo->getObjectSize(), _totalAvailable);
  }
  
private:

  static Repo<Size> *& getSource() {
    static Repo<Size> * head = nullptr;
    return head;
  }
  
};

#endif
