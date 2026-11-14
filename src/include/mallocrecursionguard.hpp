#pragma once
#ifndef MALLOCRECURSIONGUARD_H
#define MALLOCRECURSIONGUARD_H

#if defined(_WIN32)
// Use Windows-specific implementation
#include "mallocrecursionguard_win.hpp"
#else
// POSIX implementation

#include <pthread.h>

#include "common.hpp"

#if defined(__APPLE__)
#include <sys/mman.h>

#include <atomic>
#include <mutex>
#endif

/**
 * Implements a thread-specific flag to guard against inadvertent recursions
 * when interposing heap functions.
 *
 * Every interposed malloc, free and memcpy constructs one of these, so the
 * flag has to be cheap to reach: once a thread is set up, reading and
 * writing it are plain memory accesses. (It used to live directly in a
 * pthread key, which cost one pthread_getspecific and two
 * pthread_setspecific calls per allocation -- a large share of Scalene's
 * per-allocation overhead.)
 */
class MallocRecursionGuard {
#if !defined(__APPLE__)
  // libscalene is LD_PRELOADed, so initial-exec TLS lives in the static TLS
  // block: accessing it is a single thread-pointer-relative load or store,
  // and can never allocate (Heap-Layers' ThreadSpecificHeap relies on the
  // same thing).
  static inline bool& flag() {
    static __thread bool inMalloc __attribute__((tls_model("initial-exec"))) =
        false;
    return inMalloc;
  }
#else
  // On macOS, C/C++ thread-locals are allocated lazily by dyld *via malloc*
  // on a thread's first access, which would re-enter the interposer before
  // the flag exists. So the flag lives in a slot from our own mmap'd pool,
  // and a pthread key (whose storage never allocates once created) points
  // each thread at its slot. Only the first access per thread takes the
  // slow path.
  // One cache line per slot (128 bytes on Apple Silicon). Every allocation
  // writes its thread's flag twice, so slots of threads running in parallel
  // (free-threaded Python, native threads) must not share a line, or the
  // line ping-pongs between cores on every malloc and free.
  struct alignas(128) Slot {
    bool inMalloc;
    Slot* next;  // free-list link while the slot is unused
  };
  static_assert(sizeof(Slot) == 128, "one slot per cache line");

  // Seen by a thread while its own slot is being set up, and while the key
  // itself is being created (pthread_key_create may call malloc): reports
  // "already in malloc", so nested allocations are passed straight through.
  static Slot* busySlot() {
    static Slot busy{true, nullptr};
    return &busy;
  }

  static pthread_key_t* getKey() {
    static pthread_key_t _inMallocKey;
    return &_inMallocKey;
  }

  enum { NEEDS_KEY = 0, CREATING_KEY = 1, DONE = 2 };

  static int& keyState() {
    static int inMallocKeyState{NEEDS_KEY};
    return inMallocKeyState;
  }

  // Guards the pool. Only taken on a thread's first access and at thread
  // exit; busySlot() keeps a nested allocation on the same thread from
  // re-entering.
  static std::atomic_flag& poolLock() {
    static std::atomic_flag lock = ATOMIC_FLAG_INIT;
    return lock;
  }
  static Slot*& freeList() {
    static Slot* head = nullptr;
    return head;
  }

  static void lockPool() {
    while (poolLock().test_and_set(std::memory_order_acquire)) {
    }
  }
  static void unlockPool() { poolLock().clear(std::memory_order_release); }

  // Runs at thread exit with the thread's slot: recycle it.
  static void releaseSlot(void* p) {
    auto* slot = static_cast<Slot*>(p);
    if (slot == nullptr || slot == busySlot()) {
      return;
    }
    lockPool();
    slot->next = freeList();
    freeList() = slot;
    unlockPool();
  }

  static Slot* newSlot() {
    lockPool();
    Slot* slot = freeList();
    if (slot == nullptr) {
      // Carve a fresh chunk into slots. mmap never calls malloc.
      constexpr size_t kChunk = 64 * 1024;
      void* mem = mmap(nullptr, kChunk, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANON, -1, 0);
      if (mem == MAP_FAILED) {
        unlockPool();
        return nullptr;
      }
      auto* slots = static_cast<Slot*>(mem);
      const size_t n = kChunk / sizeof(Slot);
      for (size_t i = 0; i + 1 < n; i++) {
        slots[i].next = &slots[i + 1];
      }
      slots[n - 1].next = nullptr;
      slot = slots;
    }
    freeList() = slot->next;
    unlockPool();
    slot->inMalloc = false;
    slot->next = nullptr;
    return slot;
  }

  static ATTRIBUTE_NEVER_INLINE Slot* slowPath() {
    // modified double-checked locking pattern
    // (https://en.wikipedia.org/wiki/Double-checked_locking)
    static std::recursive_mutex m;
    if (__atomic_load_n(&keyState(), __ATOMIC_ACQUIRE) != DONE) {
      std::lock_guard<decltype(m)> g{m};
      auto state = __atomic_load_n(&keyState(), __ATOMIC_RELAXED);
      if (state == CREATING_KEY) {
        // Re-entered from pthread_key_create's own allocation.
        return busySlot();
      }
      if (state == NEEDS_KEY) {
        __atomic_store_n(&keyState(), CREATING_KEY, __ATOMIC_RELAXED);
        if (pthread_key_create(getKey(), releaseSlot) != 0) {  // may malloc
          abort();
        }
        __atomic_store_n(&keyState(), DONE, __ATOMIC_RELEASE);
      }
    }
    auto* slot = static_cast<Slot*>(pthread_getspecific(*getKey()));
    if (slot != nullptr) {
      return slot;
    }
    // First access on this thread. Anything that allocates in here (or a
    // signal handler that does) sees busySlot() and passes straight
    // through instead of recursing.
    pthread_setspecific(*getKey(), busySlot());
    slot = newSlot();
    if (slot == nullptr) {
      // Out of memory for slots: leave the thread on busySlot(), which only
      // stops its allocations from being sampled.
      return busySlot();
    }
    pthread_setspecific(*getKey(), slot);
    return slot;
  }

  static inline bool& flag() {
    if (likely(__atomic_load_n(&keyState(), __ATOMIC_ACQUIRE) == DONE)) {
      auto* slot = static_cast<Slot*>(pthread_getspecific(*getKey()));
      if (likely(slot != nullptr)) {
        return slot->inMalloc;
      }
    }
    return slowPath()->inMalloc;
  }
#endif

  bool* _flag;
  bool _wasInMalloc;

  MallocRecursionGuard(const MallocRecursionGuard&) = delete;
  MallocRecursionGuard& operator=(const MallocRecursionGuard&) = delete;

 public:
  inline MallocRecursionGuard() : _flag(&flag()) {
    if (!(_wasInMalloc = *_flag)) {
      *_flag = true;
    }
  }

  inline ~MallocRecursionGuard() {
    if (!_wasInMalloc) {
      *_flag = false;
    }
  }

  inline bool wasInMalloc() const { return _wasInMalloc; }

  // Mark this thread as inside Scalene's own code, so the interposed
  // malloc/free/memcpy don't sample what it does; returns the previous
  // state for resume(). Async-signal-safe once the thread has allocated
  // (Linux: initial-exec TLS; macOS: its slot already exists).
  static inline bool suspend() {
    bool& f = flag();
    bool was = f;
    f = true;
    return was;
  }
  static inline void resume(bool was) {
    if (!was) {
      flag() = false;
    }
  }
};

#endif  // !_WIN32

#endif  // MALLOCRECURSIONGUARD_H
