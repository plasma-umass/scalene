#include <heaplayers.h>

#include "stprintf.h"
#include "tprintf.h"
#include "common.hpp"

#include "mmaparray.hpp"
#include "dynarray.hpp"
#include "stack.hpp"
#include "buffer.hpp"
#include "classwarfare.hpp"
#include "bufferbump.hpp"
#include "cheapheap.hpp"
#include "sampleheap.hpp"

#include "repoman.hpp"

#include <stdio.h>
#include <execinfo.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>


#if defined(__APPLE__)
#include "macinterpose.h"
#include "tprintf.h"
#endif

class TheCustomHeap;
static TheCustomHeap * theCustomHeap = nullptr;

// We use prime numbers here (near 1MB, for example) to avoid the risk
// of stride behavior interfering with sampling.

const auto MallocSamplingRate = 1048583UL;
const auto MemcpySamplingRate = MallocSamplingRate * 2;
//const auto MallocSamplingRate = 4194319;
//const auto MallocSamplingRate = 8388617;
//const auto MallocSamplingRate = 16777259;
const auto RepoSize = 4096;

typedef SampleHeap<MallocSamplingRate, RepoMan<RepoSize>> CustomHeapType;

class TheCustomHeap : public CustomHeapType {
  typedef CustomHeapType Super;
public:
  TheCustomHeap()
  {
    theCustomHeap = this;
  }
};


TheCustomHeap& getTheCustomHeap() {
  static TheCustomHeap thang;
  return thang;
}


#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h> // for getpid()
#include <signal.h>

template <unsigned long MemcpySamplingRateBytes>
class MemcpySampler {
  enum { MemcpySignal = SIGPROF };
  static constexpr auto flags = O_WRONLY | O_CREAT | O_SYNC | O_APPEND; // O_TRUNC;
  static constexpr auto perms = S_IRUSR | S_IWUSR;
  static constexpr auto fname = "/tmp/scalene-memcpy-signalXXXXX";
public:
  MemcpySampler()
    : _interval (MemcpySamplingRateBytes),
      _memcpyOps (0),
      _memcpyTriggered (0)
  {
    signal(MemcpySignal, SIG_IGN);
    auto pid = getpid();
    int i;
    for (i = 0; i < strlen(fname); i++) {
      if (fname[i] == 'X') {
	break;
      }
      scalene_memcpy_signal_filename[i] = fname[i];
    }
    stprintf::stprintf((char *) &scalene_memcpy_signal_filename[i], "@", pid);
  }

  ~MemcpySampler() {
    unlink(scalene_memcpy_signal_filename);
  }

  ATTRIBUTE_ALWAYS_INLINE inline void * memcpy(void * dst, const void * src, size_t n) {
    auto result = ::memcpy(dst, src, n);
    _memcpyOps += n;
    if (unlikely(_memcpyOps >= _interval)) {
      writeCount();
      _memcpyTriggered++;
      _memcpyOps = 0;
      raise(MemcpySignal);
    }
    return result; // always dst
  }
  
private:
  
  unsigned long _memcpyOps;
  unsigned long long _memcpyTriggered;
  unsigned long _interval;
  char scalene_memcpy_signal_filename[255];

  void writeCount() {
    char buf[255];
    stprintf::stprintf(buf, "@,@\n", _memcpyTriggered, _memcpyOps);
    int fd = open(scalene_memcpy_signal_filename, flags, perms);
    write(fd, buf, strlen(buf));
    close(fd);
  }
};

extern "C" ATTRIBUTE_EXPORT void * xxmemcpy(void * dst, const void * src, size_t n) {
  static MemcpySampler<MemcpySamplingRate> msamp;
  //  tprintf::tprintf("E");
  auto result = msamp.memcpy(dst, src, n);
  //  tprintf::tprintf("F\n");
  return result;
}

#if defined(__APPLE__)
MAC_INTERPOSE(xxmemcpy, memcpy);
#endif

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void * xxmalloc(size_t sz) {
  void * ptr = nullptr;
  if (theCustomHeap) {
    ptr = theCustomHeap->malloc(sz);
  } else {
    ptr = getTheCustomHeap().malloc(sz);
  }
  return ptr;
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxfree(void * ptr) {
  theCustomHeap->free(ptr);
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxfree_sized(void * ptr, size_t sz) {
  // TODO FIXME maybe make a sized-free version?
  getTheCustomHeap().free(ptr);
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) size_t xxmalloc_usable_size(void * ptr) {
  return theCustomHeap->getSize(ptr); // TODO FIXME adjust for ptr offset?
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxmalloc_lock() {
}

extern "C" ATTRIBUTE_EXPORT __attribute__((always_inline)) void xxmalloc_unlock() {
}
