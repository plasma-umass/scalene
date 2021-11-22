#pragma once
#ifndef MALLOCRECURSIONGUARD_H
#define MALLOCRECURSIONGUARD_H

#include <pthread.h>

#include <mutex>

#include "common.hpp"

/**
 * Implements a thread-specific flag to guard against inadventernt recursions
 * when interposing heap functions.
 */
class MallocRecursionGuard {
  static pthread_key_t* getKey() {
    static pthread_key_t _inMallocKey;
    return &_inMallocKey;
  }

  static bool isInMalloc() {
    // modified double-checked locking pattern
    // (https://en.wikipedia.org/wiki/Double-checked_locking)
    static enum {
      NEEDS_KEY = 0,
      CREATING_KEY = 1,
      DONE = 2
    } inMallocKeyState{NEEDS_KEY};
    static std::recursive_mutex m;

    // We create the thread-specific data store the pthread way because the C++
    // language based ones all seem to fail when interposing on malloc et al, as
    // they are invoked early from within library initialization.

    auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_ACQUIRE);
    if (state != DONE) {
      std::lock_guard<decltype(m)> g{m};

      state = __atomic_load_n(&inMallocKeyState, __ATOMIC_RELAXED);
      if (unlikely(state == CREATING_KEY)) {
        return true;
      } else if (unlikely(state == NEEDS_KEY)) {
        __atomic_store_n(&inMallocKeyState, CREATING_KEY, __ATOMIC_RELAXED);
        if (pthread_key_create(getKey(), 0) !=
            0) {  // may call malloc/calloc/...
          abort();
        }
        __atomic_store_n(&inMallocKeyState, DONE, __ATOMIC_RELEASE);
      }
    }

    return pthread_getspecific(*getKey()) != 0;
  }

  static void setInMalloc(bool state) {
    pthread_setspecific(*getKey(), state ? (void*)1 : (void*)0);
  }

  bool _wasInMalloc;

  MallocRecursionGuard(const MallocRecursionGuard&) = delete;
  MallocRecursionGuard& operator=(const MallocRecursionGuard&) = delete;

 public:
  MallocRecursionGuard() {
    if (!(_wasInMalloc = isInMalloc())) {
      setInMalloc(true);
    }
  }

  ~MallocRecursionGuard() {
    if (!_wasInMalloc) {
      setInMalloc(false);
    }
  }

  bool wasInMalloc() const { return _wasInMalloc; }
};

#endif
