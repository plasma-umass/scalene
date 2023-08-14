#pragma once
#ifndef MALLOCRECURSIONGUARD_H
#define MALLOCRECURSIONGUARD_H

#include <pthread.h>

#include <mutex>

#include "common.hpp"

/**
 * Implements a thread-specific flag to guard against inadvertent recursions
 * when interposing heap functions.
 */
class MallocRecursionGuard {
  static pthread_key_t* getKey() {
    static pthread_key_t _inMallocKey;
    return &_inMallocKey;
  }

  enum { NEEDS_KEY = 0, CREATING_KEY = 1, DONE = 2 };

  static inline bool isInMalloc() {
    // modified double-checked locking pattern
    // (https://en.wikipedia.org/wiki/Double-checked_locking)
    static std::recursive_mutex m;
    static int inMallocKeyState{NEEDS_KEY};

    // We create the thread-specific data store the pthread way because the C++
    // language based ones all seem to fail when interposing on malloc et al.,
    // as they are invoked early from within library initialization.

    auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_ACQUIRE);
    if (state != DONE) {
      if (slowPathInMalloc(m, inMallocKeyState) == CREATING_KEY) {
        // this happens IFF pthread_key_create allocates memory
        return true;
      }
    }

    return pthread_getspecific(*getKey()) != 0;
  }

  static int slowPathInMalloc(std::recursive_mutex& m, int& inMallocKeyState) {
    std::lock_guard<decltype(m)> g{m};

    auto state = __atomic_load_n(&inMallocKeyState, __ATOMIC_RELAXED);

    if (unlikely(state == NEEDS_KEY)) {
      __atomic_store_n(&inMallocKeyState, CREATING_KEY, __ATOMIC_RELAXED);
      if (pthread_key_create(getKey(), 0) != 0) {  // may call [cm]alloc
        abort();
      }
      __atomic_store_n(&inMallocKeyState, DONE, __ATOMIC_RELEASE);
      return DONE;
    }

    return state;
  }

  static inline void setInMalloc(bool state) {
    pthread_setspecific(*getKey(), state ? (void*)1 : (void*)0);
  }

  bool _wasInMalloc;

  MallocRecursionGuard(const MallocRecursionGuard&) = delete;
  MallocRecursionGuard& operator=(const MallocRecursionGuard&) = delete;

 public:
  inline MallocRecursionGuard() {
    if (!(_wasInMalloc = isInMalloc())) {
      setInMalloc(true);
    }
  }

  inline ~MallocRecursionGuard() {
    if (!_wasInMalloc) {
      setInMalloc(false);
    }
  }

  inline bool wasInMalloc() const { return _wasInMalloc; }
};

#endif
