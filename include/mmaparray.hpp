#ifndef MMAP_ARRAY_H
#define MMAP_ARRAY_H

#include <sys/mman.h>

class MmapArray {
 public:
  static void *map(size_t sz) {
    //    std::lock_guard guard (_mutex);
    void *ptr = mmap((void *)0, sz, PROT_READ | PROT_WRITE,
                     MAP_ANON | MAP_PRIVATE | MAP_NORESERVE, -1, 0);
    if (ptr == MAP_FAILED) {
      return nullptr;
    }
    return ptr;
  }
  static void unmap(void *buf, size_t sz) { munmap(buf, sz); }
};

#endif
