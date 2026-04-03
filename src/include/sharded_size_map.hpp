#pragma once

#ifndef SHARDED_SIZE_MAP_HPP
#define SHARDED_SIZE_MAP_HPP

// Out-of-band allocation size tracking for free-threaded Python.
//
// On free-threaded Python, ScaleneHeader cannot be prepended to allocations
// because the GC directly scans mimalloc heap pages expecting valid Python
// objects. This sharded hash table tracks ptr -> size out of band so that
// local_free() can recover the allocation size for accurate sampling.
//
// Design: 128 shards, each with a spinlock and an open-addressed flat
// hash table using linear probing.  Per-entry cost is 16 bytes (two
// pointers), matching ScaleneHeader's overhead.  No heap allocation for
// individual entries — only bulk array resizes on growth.

#ifdef Py_GIL_DISABLED

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

class ShardedSizeMap {
  static constexpr unsigned NUM_SHARDS = 128;
  // Initial capacity per shard (must be power of 2).
  static constexpr size_t INIT_CAPACITY = 1024;
  // Grow when load exceeds 70%.
  static constexpr unsigned LOAD_PERCENT = 70;

  struct SpinLock {
    std::atomic_flag flag = ATOMIC_FLAG_INIT;
    void lock() { while (flag.test_and_set(std::memory_order_acquire)) {} }
    void unlock() { flag.clear(std::memory_order_release); }
  };

  // Each slot is 16 bytes: a pointer and a size.
  // ptr == nullptr means the slot is empty.
  struct Slot {
    void* ptr;
    size_t size;
  };

  struct Shard {
    SpinLock lock;
    Slot* slots;
    size_t capacity;  // always a power of 2
    size_t count;     // number of occupied slots

    Shard() : slots(nullptr), capacity(0), count(0) {}

    ~Shard() {
      ::free(slots);
    }

    void ensure_capacity() {
      if (slots == nullptr) {
        capacity = INIT_CAPACITY;
        slots = (Slot*)::calloc(capacity, sizeof(Slot));
      }
    }

    void grow() {
      size_t new_cap = capacity * 2;
      Slot* new_slots = (Slot*)::calloc(new_cap, sizeof(Slot));
      size_t mask = new_cap - 1;
      // Rehash all existing entries.
      for (size_t i = 0; i < capacity; i++) {
        if (slots[i].ptr != nullptr) {
          size_t idx = ((uintptr_t)slots[i].ptr >> 4) & mask;
          while (new_slots[idx].ptr != nullptr) {
            idx = (idx + 1) & mask;
          }
          new_slots[idx] = slots[i];
        }
      }
      ::free(slots);
      slots = new_slots;
      capacity = new_cap;
    }
  };

  Shard shards_[NUM_SHARDS];

  static unsigned shard_index(void* ptr) {
    return ((uintptr_t)ptr >> 4) & (NUM_SHARDS - 1);
  }

 public:
  void insert(void* ptr, size_t size) {
    auto& s = shards_[shard_index(ptr)];
    s.lock.lock();
    s.ensure_capacity();
    // Grow if load factor exceeded.
    if (s.count * 100 >= s.capacity * LOAD_PERCENT) {
      s.grow();
    }
    size_t mask = s.capacity - 1;
    size_t idx = ((uintptr_t)ptr >> 4) & mask;
    while (s.slots[idx].ptr != nullptr) {
      if (s.slots[idx].ptr == ptr) {
        // Update existing entry (e.g. realloc to same address).
        s.slots[idx].size = size;
        s.lock.unlock();
        return;
      }
      idx = (idx + 1) & mask;
    }
    s.slots[idx].ptr = ptr;
    s.slots[idx].size = size;
    s.count++;
    s.lock.unlock();
  }

  size_t remove(void* ptr) {
    auto& s = shards_[shard_index(ptr)];
    s.lock.lock();
    if (s.slots == nullptr) {
      s.lock.unlock();
      return 0;
    }
    size_t mask = s.capacity - 1;
    size_t idx = ((uintptr_t)ptr >> 4) & mask;
    while (s.slots[idx].ptr != nullptr) {
      if (s.slots[idx].ptr == ptr) {
        size_t sz = s.slots[idx].size;
        // Delete via backward-shift to keep the probe chain intact.
        size_t hole = idx;
        for (;;) {
          size_t next = (hole + 1) & mask;
          if (s.slots[next].ptr == nullptr) {
            break;
          }
          // Where does the entry at `next` naturally belong?
          size_t natural = ((uintptr_t)s.slots[next].ptr >> 4) & mask;
          // Check if `natural` is NOT in (hole, next] (wrapping).
          // If so, the entry at `next` can fill the hole.
          bool should_move;
          if (hole < next) {
            should_move = (natural <= hole || natural > next);
          } else {
            // Wrapped around: hole is near the end, next is near start.
            should_move = (natural <= hole && natural > next);
          }
          if (should_move) {
            s.slots[hole] = s.slots[next];
            hole = next;
          } else {
            break;
          }
        }
        s.slots[hole].ptr = nullptr;
        s.slots[hole].size = 0;
        s.count--;
        s.lock.unlock();
        return sz;
      }
      idx = (idx + 1) & mask;
    }
    s.lock.unlock();
    return 0;
  }
};

#endif  // Py_GIL_DISABLED

#endif  // SHARDED_SIZE_MAP_HPP
