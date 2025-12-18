#pragma once
#ifndef MALLOCRECURSIONGUARD_WIN_H
#define MALLOCRECURSIONGUARD_WIN_H

#if defined(_WIN32)

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <mutex>

#include "common_win.hpp"

/**
 * Windows-specific implementation of MallocRecursionGuard
 * Uses Windows TLS (Thread Local Storage) instead of pthread_key_t
 */
class MallocRecursionGuard {
  static DWORD* getTlsIndex() {
    static DWORD _tlsIndex = TLS_OUT_OF_INDEXES;
    return &_tlsIndex;
  }

  enum { NEEDS_KEY = 0, CREATING_KEY = 1, DONE = 2 };

  static inline bool isInMalloc() {
    static std::recursive_mutex m;
    static volatile long inMallocKeyState = NEEDS_KEY;

    auto state = InterlockedCompareExchange(&inMallocKeyState, inMallocKeyState, inMallocKeyState);
    if (state != DONE) {
      if (slowPathInMalloc(m, inMallocKeyState) == CREATING_KEY) {
        return true;
      }
    }

    DWORD tlsIndex = *getTlsIndex();
    if (tlsIndex == TLS_OUT_OF_INDEXES) {
      return false;
    }
    return TlsGetValue(tlsIndex) != 0;
  }

  static int slowPathInMalloc(std::recursive_mutex& m, volatile long& inMallocKeyState) {
    std::lock_guard<decltype(m)> g{m};

    auto state = InterlockedCompareExchange(&inMallocKeyState, inMallocKeyState, inMallocKeyState);

    if (unlikely(state == NEEDS_KEY)) {
      InterlockedExchange(&inMallocKeyState, CREATING_KEY);
      DWORD idx = TlsAlloc();
      if (idx == TLS_OUT_OF_INDEXES) {
        // TlsAlloc failed - could be out of slots
        // Fall back to non-threadsafe static
        InterlockedExchange(&inMallocKeyState, DONE);
        return DONE;
      }
      *getTlsIndex() = idx;
      InterlockedExchange(&inMallocKeyState, DONE);
      return DONE;
    }

    return state;
  }

  static inline void setInMalloc(bool state) {
    DWORD tlsIndex = *getTlsIndex();
    if (tlsIndex != TLS_OUT_OF_INDEXES) {
      TlsSetValue(tlsIndex, state ? (LPVOID)1 : (LPVOID)0);
    }
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

#endif // _WIN32

#endif // MALLOCRECURSIONGUARD_WIN_H
