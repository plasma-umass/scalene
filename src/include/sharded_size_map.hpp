#pragma once

#ifndef SHARDED_SIZE_MAP_HPP
#define SHARDED_SIZE_MAP_HPP

// Out-of-band allocation size tracking for free-threaded Python.
//
// On free-threaded Python, ScaleneHeader cannot be prepended to allocations
// because the GC directly scans mimalloc heap pages expecting valid Python
// objects. This sharded hash table tracks ptr -> size out of band so that
// local_free() can recover the allocation size for accurate sampling.

#ifdef Py_GIL_DISABLED

#include <cstddef>
#include <cstdint>
#include <unordered_map>

#include "spinlock.h"

class ShardedSizeMap {
  static constexpr unsigned NUM_SHARDS = 128;

  struct Shard {
    HL::SpinLockType lock;
    std::unordered_map<void*, size_t> map;
  };

  Shard shards_[NUM_SHARDS];

  Shard& shard_for(void* ptr) {
    // Shift right by 4 because mimalloc aligns to at least 16 bytes.
    auto idx = ((uintptr_t)ptr >> 4) & (NUM_SHARDS - 1);
    return shards_[idx];
  }

 public:
  void insert(void* ptr, size_t size) {
    auto& s = shard_for(ptr);
    s.lock.lock();
    s.map[ptr] = size;
    s.lock.unlock();
  }

  size_t remove(void* ptr) {
    auto& s = shard_for(ptr);
    s.lock.lock();
    size_t sz = 0;
    auto it = s.map.find(ptr);
    if (it != s.map.end()) {
      sz = it->second;
      s.map.erase(it);
    }
    s.lock.unlock();
    return sz;
  }
};

#endif  // Py_GIL_DISABLED

#endif  // SHARDED_SIZE_MAP_HPP
