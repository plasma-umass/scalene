#pragma once

//#include "chunkallocator.hpp"
#include "mmapallocator.hpp"
#include "parallel_hashmap/phmap.h"

class SizeManager {
public:
  SizeManager() {
  }
  void setSize(void * ptr, size_t sz) {
    sizeMap[ptr] = sz;
  }
  size_t getSize(void * ptr) const {
    decltype(getSize(nullptr)) sz = 0;
    auto it = sizeMap.find(ptr);
    if (it != sizeMap.end()) {
      sz = it->second;
    }
    return sz;
  }
  void clearSize(void * ptr) {
    sizeMap.erase(ptr);
  }
private:
  SizeManager(const SizeManager&) = delete;  
  SizeManager& operator=(SizeManager const&) = delete;
  using Map = phmap::parallel_flat_hash_map<const void *, std::size_t,
					    std::hash<const void *>,
					    std::equal_to<const void *>, 
					    MmapAllocator<std::pair<const void *, size_t>>, 
					    1,
					    std::mutex>;
  Map sizeMap;
};
