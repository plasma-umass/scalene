#ifndef SCALENE_HEADER_H
#define SCALENE_HEADER_H

#include <stddef.h>
#if defined(__SVR4)
extern "C" size_t malloc_usable_size(void *);
#elif defined(__APPLE__)
#include <malloc/malloc.h>
#elif defined(__linux__)
#include <malloc.h>
#else
extern "C" size_t malloc_usable_size(void *) throw();
#endif
#include <assert.h>

#define USE_HEADERS 1
#define DEBUG_HEADER 0

#if DEBUG_HEADERS
const int n_padding = 16 - 2 * sizeof(size_t);
#else
const int n_padding = 16 - sizeof(size_t);
#endif
// Maximum size allocated internally by pymalloc;
// aka "SMALL_REQUEST_THRESHOLD" in cpython/Objects/obmalloc.c
#define PYMALLOC_MAX_SIZE 512

class ScaleneHeader {
 private:
  static constexpr size_t MAGIC_NUMBER = 0x01020304;
  // NOTE-- this header MUST be a multiple of 16 bytes in length
  // because of the expectation of the Python interpreter. The unmodified
  // interpreter may opt at compile-time to use 8 or 16 byte alignments, but we
  // opt for 16 to cover both cases
 public:
#if USE_HEADERS
#if DEBUG_HEADER
  ScaleneHeader(size_t sz) : size(sz), magic(MAGIC_NUMBER) {}
  size_t size;

  size_t magic;
  uint8_t padding[n_padding];
#else
  ScaleneHeader(size_t sz) : size(sz) {}
  size_t size;
  uint8_t padding[n_padding];

#endif
#else
  ScaleneHeader(size_t) {}

#endif

  static inline ScaleneHeader *getHeader(void *ptr) {
#if USE_HEADERS
    return (ScaleneHeader *)ptr - 1;
#else
    return (ScaleneHeader *)ptr;
#endif
  }

  static inline size_t getSize(void *ptr) {
#if USE_HEADERS
#if DEBUG_HEADER
    assert(getHeader(ptr)->magic == MAGIC_NUMBER);
#endif
    auto sz = getHeader(ptr)->size;
    if (sz > PYMALLOC_MAX_SIZE) {
#if defined(__APPLE__)
      assert(::malloc_size(getHeader(ptr)) >= sz);
#else
      assert(::malloc_usable_size(getHeader(ptr)) >= sz);
#endif
    }
    return sz;
#else
    return 123;  // Bogus size.
#endif
  }

  static inline void setSize(void *ptr, size_t sz) {
#if USE_HEADERS
    auto h = getHeader(ptr);
#if DEBUG_HEADER
    h->magic = MAGIC_NUMBER;
#endif
    h->size = sz;
#endif
  }

  static inline void *getObject(ScaleneHeader *header) {
#if USE_HEADERS
    return (void *)(header + 1);
#else
    return (void *)header;
#endif
  }
};
#endif
