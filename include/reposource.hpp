#ifndef REPOSOURCE_HPP
#define REPOSOURCE_HPP

#include "repo.hpp"

template <int Size>
class RepoSource {
private:

  char * _buf;
  size_t _sz;
  
public:

  RepoSource(char * buf, size_t sz)
    : _buf (buf),
      _sz (sz)
  {}
  
  Repo<Size> * get(size_t sz) {
    Repo<Size> * repo = nullptr;
    if (getSource(sz) == nullptr) {
      // Allocate a new one. FIXME ensure alignment.
      if (sz < _sz) {
	auto buf = _buf;
	_buf += Size;
	_sz -= Size;
	//      auto buf = MmapWrapper::map(Size);
	// Must ensure sz is a proper size.
	repo = new (buf) Repo<Size>(sz);
      } else {
	return nullptr;
      }
    } else {
      repo = getSource(sz);
      getSource(sz) = (Repo<Size> *)(((RepoHeader<Size> *) getSource(sz))->_next);
      if (getSource() != nullptr) {
	assert(getSource()->isValid());
	assert(getSource()->isEmpty());
      }
    }
    repo->_next = nullptr;
    assert(repo->isValid());
    assert(repo->isEmpty());
    ///    tprintf::tprintf("GET @ = @\n", sz, repo);
    return repo;
  }

  void put(Repo<Size> * repo) {
    ///    tprintf::tprintf("PUT @ (sz = @)\n", repo, repo->_objectSize);
    Repo<Size> * r = getSource();
    while (r != nullptr) {
      assert (r != repo);
      r = (Repo<Size> *) r->_next;
    }
    assert(repo->isValid());
    assert(repo->isEmpty());
    //    assert(getSource() == nullptr || getSource()->isEmpty());
    repo->_next = getSource();
    getSource() = repo;
  }
  
private:

  static Repo<Size> *& getSource(size_t sz = 0) {
    static Repo<Size> * head = nullptr;
    if (head != nullptr) {
      if (sz > 0) {
	head->_objectSize = sz;
      }
    }
    return head;
  }
  
};

#endif
