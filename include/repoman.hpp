#ifndef REPOMAN_HPP
#define REPOMAN_HPP

#include "repo.hpp"
#include "heaplayers.h"

#include <new>
#include <iostream>
#include <stdlib.h>

//     int posix_memalign(void **memptr, size_t alignment, size_t size);


template <int From, int Iterations, template <int, int> class C, int Arg, typename V>
class StaticForLoop;

template <int From, template <int, int> class C, int Arg, typename V>
class StaticForLoop<From, 0, C, Arg, V>
{
public:
  static void run (V) {}
};

template <int From, int Iterations, template <int, int> class C, int Arg, typename V>
class StaticForLoop {
public:
  static void run (V v)
  {
    C<From, Arg>::run (v);
    StaticForLoop<From+1, Iterations-1, C, Arg, V> s;
    // Silly workaround for Sun.
    s.run (v);
  }
};

template <int index, int Size>
class RepoManInitializer {
public:
  static void run (void * buf) {
    auto ptr = reinterpret_cast<void *>((char *) buf + Size * index);
    //    std::cout << "ptr = " << ptr << std::endl;
    new (ptr) Repo<(index + 1) * 8, Size>();
    //    std::cout << "initialized " << index << ", repo size = " << repo->getBaseSize() << std::endl;
  }
};
 


template <int Size>
class RepoMan {
public:

  // FIXME static assert that Size is a power of two.
  
  RepoMan()
  {
    // FIXME need to guarantee alignment.
    repos = reinterpret_cast<RepoBase<Size> *>(MmapWrapper::map(Size / 8 * Size));
    //    std::cout << "repos = " << repos << std::endl;
    
    //    posix_memalign((void **) &repos, Size, Size/8 * Size);
    //    std::cout << "repos = " << repos << std::endl;
    //    StaticForLoop<0, Size/8, RepoManInitializer, void *>::run((void *) repos);
    StaticForLoop<0, 512/8, RepoManInitializer, Size, void *>::run((void *) repos);
  }

  void * malloc(size_t sz) {
    if (sz == 0) { sz = 1; }
    if (sz <= 512) {
      int index = sz / 8 - 1;
      //    std::cout << "repos[index] = " << &repos[index] << std::endl;
      return repos[index].malloc(sz);
    } else {
      // For now, allocate directly via mmap.
      // Add the space for the header metadata.
      sz = sz + sizeof(RepoHeader);
      // Round sz up to next multiple of Size.
      sz = (sz + Size - 1) & ~(Size - 1);
      //      std::cout << "allocating object of size " << sz << std::endl;
      // FIXME force alignment!
      auto basePtr = MmapWrapper::map(sz);
      new (basePtr) RepoHeader(sz);
      void * ptr = reinterpret_cast<char *>(basePtr) + sizeof(RepoHeader);
      //      std::cout << "object size = " << getSize(ptr) << ", ptr = " << ptr << std::endl;
      return ptr;
    }
  }
  
  void free(void * ptr) {
    if (ptr != nullptr) {
      //      std::cout << "checking " << ptr << std::endl;
      auto sz = getSize(ptr);
      if (sz <= 512) {
	int index = sz / 8 - 1;
	repos[index].free(ptr);
      } else {
	//	std::cout << "freeing obj of size " << sz << std::endl;
	auto basePtr = reinterpret_cast<char *>(ptr) - sizeof(RepoHeader);
	MmapWrapper::unmap(reinterpret_cast<RepoHeader *>(basePtr), sz);
      }
    }
  }

  size_t getSize(void * ptr) {
    auto headerPtr = (RepoHeader *) ((uintptr_t) ptr & ~(Size-1));
    //    std::cout << "headerPtr = " << (void *) headerPtr << ", ptr = " << ptr << std::endl;
    return headerPtr->getBaseSize();
  }
  
private:
  
  RepoBase<Size> * repos;
  
};

#endif
