#pragma once

/**
 * open_addr_hashtable: simple hash table that does no allocation.
 * Emery Berger
 * https://emeryberger.com
 **/

#include <stdint.h>

template <unsigned long Size>
class open_addr_hashtable {
 public:
  open_addr_hashtable() {
    static_assert((Size & (Size - 1UL)) == 0, "Size must be a power of two.");
  }

  void *get(void *k) {
    auto ind = find(k);
    if (ind == -1) {
      return nullptr;
    } else {
      return payload[ind].value;
    }
  }

  void put(void *k, void *v) {
    auto h = hash1(k) & (Size - 1UL);
    if (payload[h].key == nullptr) {
      payload[h].key = k;
    }
    if (payload[h].key == k) {
      payload[h].value = v;
      return;
    }
    while (true) {
      h = (h + hash2((void *)h)) & (Size - 1UL);
      if (payload[h].key == nullptr) {
        payload[h].key = k;
      }
      if (payload[h].key == k) {
        payload[h].value = v;
        return;
      }
    }
  }

  // @return true iff the element was deleted.
  bool remove(void *k) {
    auto h = hash1(k) & (Size - 1UL);
    if (payload[h].key == nullptr) {
      // Not in the hash table.
      return false;
    }
    if (payload[h].key == k) {
      payload[h].key = nullptr;
      payload[h].value = nullptr;
      ;
      return true;
    }
    while (true) {
      h = (h + hash2((void *)h)) & (Size - 1UL);
      if (payload[h].key == nullptr) {
        return false;
      }
      if (payload[h].key == k) {
        payload[h].key = nullptr;
        payload[h].value = nullptr;
        return true;
      }
    }
  }

 private:
  // Returns -1 if not found.
  int find(void *k) {
    unsigned long h = hash1(k) & (Size - 1UL);
    if (payload[h].key == k) {
      return h;
    }
    if (payload[h].key == nullptr) {
      return -1;
    }
    while (true) {
      h = (h + hash2((void *)h) + 1) & (Size - 1UL);
      if (payload[h].key == k) {
        return h;
      }
      if (payload[h].key == nullptr) {
        return -1;
      }
    }
  }
  // Ideally, we'd use actual random numbers here,
  // but these should still do the trick.
  unsigned long hash1(void *addr) {
    auto u = (uintptr_t)addr;
    return (u ^ 0xAFB758AC3E937519);
  }
  unsigned long hash2(void *addr) {
    auto u = (uintptr_t)addr;
    return (u ^ 0x9493AFE261E39855);
  }
  struct payload_t {
    payload_t() : key(nullptr), value(nullptr) {}
    void *key;
    void *value;
  };
  payload_t payload[Size];
};
