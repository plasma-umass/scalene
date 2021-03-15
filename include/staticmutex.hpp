#pragma once

#ifndef STATICMUTEX_H
#define STATICMUTEX_H

#include <pthread.h>

#if !defined(PTHREAD_RECURSIVE_MUTEX_INITIALIZER)
  #define PTHREAD_RECURSIVE_MUTEX_INITIALIZER PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP
#endif

/**
 * Mutex class that is statically initialized and doesn't require malloc.
 */
class StaticMutex {
  pthread_mutex_t _m;

 public:
  StaticMutex(pthread_mutex_t initializer = PTHREAD_MUTEX_INITIALIZER) : _m(initializer) {}

  class Guard {
    pthread_mutex_t& _m;

   public:
    Guard(StaticMutex& m) : _m(m._m) {
      if (pthread_mutex_lock(&_m) != 0) {
        abort();
      }
    }

    ~Guard() {
      if (pthread_mutex_unlock(&_m) != 0) {
        abort();
      }
    }
  };
};

#endif
