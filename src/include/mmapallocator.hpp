#pragma once

#include <sys/mman.h>

template <typename T>
class MmapAllocator {
public:
  using value_type = T;
  
  MmapAllocator() {
  }
  
  template <typename U>
  MmapAllocator(const MmapAllocator<U>&) {}
  
  T* allocate(std::size_t n) {
    return static_cast<T*>(mmap(nullptr, n * sizeof(T), PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
  }
  
  void deallocate(T* obj, std::size_t n) {
    //    std::cerr << "deallocating " << n * sizeof(T) << std::endl;
    munmap(obj, n * sizeof(T));
  }
  
};
