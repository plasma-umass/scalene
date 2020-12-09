#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <sys/errno.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <fcntl.h>
#include <unistd.h> // for getpid()

#include <random>
#include <atomic>

#include <signal.h>

#include "common.hpp"
#include "open_addr_hashtable.hpp"
#include "sampler.hpp"
#include "stprintf.h"
#include "tprintf.h"

#define USE_ATOMICS 0

#if USE_ATOMICS
typedef std::atomic<uint64_t> counterType;
#else
typedef uint64_t counterType;
#endif

template <uint64_t MallocSamplingRateBytes, class SuperHeap> 
class SampleHeap : public SuperHeap {

  static constexpr int MAX_FILE_SIZE = 4096 * 65536;
  
public:
  
  enum { Alignment = SuperHeap::Alignment };
  enum AllocSignal { MallocSignal = SIGXCPU, FreeSignal = SIGXFSZ };
  enum { CallStackSamplingRate = MallocSamplingRateBytes * 10 }; // 10 here just to reduce overhead

  SampleHeap()
    : _mallocTriggered (0),
      _freeTriggered (0),
      _pythonCount (0),
      _cCount (0),
      _lastpos (0)
  {
    // Ignore these signals until they are replaced by a client.
    signal(MallocSignal, SIG_IGN);
    signal(FreeSignal, SIG_IGN);
    // Set up the log file.
    auto pid = getpid();
    stprintf::stprintf(scalene_malloc_signal_filename, "/tmp/scalene-malloc-signal@", pid);
    _fd = open(scalene_malloc_signal_filename, flags, perms);
    // Make it so the file can reach the maximum size.
    ftruncate(_fd, MAX_FILE_SIZE);
    _mmap = reinterpret_cast<char *>(mmap(0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, _fd, 0));
    if (_mmap == MAP_FAILED) {
      tprintf::tprintf("Scalene: internal error = @\n", errno);
      abort();
    }
  }

  ~SampleHeap() {
    // Delete the log file.
    unlink(scalene_malloc_signal_filename);
  }
  
  ATTRIBUTE_ALWAYS_INLINE inline void * malloc(size_t sz) {
    auto ptr = SuperHeap::malloc(sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    auto realSize = SuperHeap::getSize(ptr);
    assert(realSize >= sz);
    assert((sz < 16) || (realSize <= 2 * sz));
    auto sampleMalloc = _mallocSampler.sample(realSize);
    auto sampleCallStack = _callStackSampler.sample(realSize);
#if 1
    if (unlikely(sampleCallStack)) {
      recordCallStack(realSize);
    }
#endif
    if (unlikely(sampleMalloc)) {
      handleMalloc(sampleMalloc);
    }
    return ptr;
  }

  ATTRIBUTE_ALWAYS_INLINE inline void free(void * ptr) {
    if (unlikely(ptr == nullptr)) { return; }
    auto realSize = SuperHeap::getSize(ptr);
    SuperHeap::free(ptr);
    auto sampleFree = _freeSampler.sample(realSize);
    if (unlikely(sampleFree)) {
      handleFree(sampleFree);
    }
  }

  void * memalign(size_t alignment, size_t sz) {
    auto ptr = SuperHeap::memalign(alignment, sz);
    if (unlikely(ptr == nullptr)) {
      return nullptr;
    }
    auto realSize = SuperHeap::getSize(ptr);
    assert(realSize >= sz);
    assert((sz < 16) || (realSize <= 2 * sz));
    auto sampleMalloc = _mallocSampler.sample(realSize);
    auto sampleCallStack = _callStackSampler.sample(realSize);
#if 1
    if (unlikely(sampleCallStack)) {
      recordCallStack(realSize);
    }
#endif
    if (unlikely(sampleMalloc)) {
      handleMalloc(sampleMalloc);
    }
    return ptr;
  }
  
private:

  void handleMalloc(size_t sampleMalloc) {
    writeCount(MallocSignal, sampleMalloc * MallocSamplingRateBytes);
    _pythonCount = 0;
    _cCount = 0;
    _mallocTriggered++;
#if !SCALENE_DISABLE_SIGNALS
    raise(MallocSignal);
#endif
  }

  void handleFree(size_t sampleFree) {
    writeCount(FreeSignal, sampleFree * MallocSamplingRateBytes);
    _freeTriggered++;
#if !SCALENE_DISABLE_SIGNALS
    raise(FreeSignal);
#endif
  }
  
  Sampler<MallocSamplingRateBytes> _mallocSampler;
  Sampler<MallocSamplingRateBytes> _freeSampler;
  Sampler<CallStackSamplingRate>   _callStackSampler;
  counterType _mallocTriggered;
  counterType _freeTriggered;
  counterType _pythonCount;
  counterType _cCount;

  open_addr_hashtable<65536> _table; // Maps call stack entries to function names.
  char scalene_malloc_signal_filename[256];
  int _fd;       // true file descriptor for the log
  char * _mmap;  // address of the first byte of the log
  int _lastpos;  // last position written into the log
  
  void recordCallStack(size_t sz) {
    // Walk the stack to see if this memory was allocated by Python
    // through its object allocation APIs.
    const auto MAX_FRAMES_TO_CHECK = 4; // enough to skip past the replacement_malloc
    void * callstack[MAX_FRAMES_TO_CHECK];
    auto frames = backtrace(callstack, MAX_FRAMES_TO_CHECK);
    char * fn_name;
    // tprintf::tprintf("------- @ -------\n", sz);
    for (auto i = 0; i < frames; i++) {
      fn_name = nullptr;

#define USE_HASHTABLE 1
#if !USE_HASHTABLE
      auto v = nullptr;
#else
      auto v = _table.get(callstack[i]);
#endif
      if (v == nullptr) {
	// Not found. Add to table.
	Dl_info info;
	int r = dladdr(callstack[i], &info);
	if (r) {
#if !USE_HASHTABLE
#else
	  _table.put(callstack[i], (void *) info.dli_sname);
#endif
	  fn_name = (char *) info.dli_sname;
	} else {
	  continue;
	}
      } else {
	// Found it.
	fn_name = (char *) v;
      }
      if (!fn_name) {
	continue;
      }
      // tprintf::tprintf("@\n", fn_name);
      if (strlen(fn_name) < 9) { // length of PySet_New
	continue;
      }
      // Starts with Py, assume it's Python calling.
      if (strstr(fn_name, "Py") == &fn_name[0]) {
	//(strstr(fn_name, "PyList_Append") ||
	//   strstr(fn_name, "_From") ||
	//   strstr(fn_name, "_New") ||
	//   strstr(fn_name, "_Copy"))) {
	if (strstr(fn_name, "PyArray_")) {
	  // Make sure we're not in NumPy, which irritatingly exports some functions starting with "Py"...
	  // tprintf::tprintf("--NO---\n");
	  goto C_CODE;
	}
#if 0
	if (strstr(fn_name, "PyEval") || strstr(fn_name, "PyCompile") || strstr(fn_name, "PyImport")) {
	  // Ignore allocations due to interpreter internal operations, for now.
	  goto C_CODE;
	}
#endif
	// tprintf::tprintf("P\n");
	_pythonCount += sz;
	return;
      }
      if (strstr(fn_name, "_Py") == 0) {
	continue;
      }
      if (strstr(fn_name, "_PyCFunction")) {
	goto C_CODE;
      }
#if 1
      _pythonCount += sz;
      return;
#else
      // TBD: realloc requires special handling.
      // * _PyObject_Realloc
      // * _PyMem_Realloc
      if (strstr(fn_name, "New")) {
	// tprintf::tprintf("P\n");
	_pythonCount += sz;
	return;
      }
      if (strstr(fn_name, "_PyObject_") ) {
	if ((strstr(fn_name, "GC_Alloc") ) ||
	    (strstr(fn_name, "GC_New") ) ||
	    (strstr(fn_name, "GC_NewVar") ) ||
	    (strstr(fn_name, "GC_Resize") ) ||
	    (strstr(fn_name, "Malloc") ) ||
	    (strstr(fn_name, "Calloc") ))	      
	  {
	    // tprintf::tprintf("P\n");
	    _pythonCount += sz;
	    return;
	  }
      }
      if (strstr(fn_name, "_PyMem_") ) {
	if ((strstr(fn_name, "Malloc") ) ||
	    (strstr(fn_name, "Calloc") ) ||
	    (strstr(fn_name, "RawMalloc") ) ||
	    (strstr(fn_name, "RawCalloc") ))
	  {
	    // tprintf::tprintf("p\n");
	    _pythonCount += sz;
	    return;
	  }
      }
      //      tprintf::tprintf("@\n", fn_name);
#endif	  
    }
    
  C_CODE:
    _cCount += sz;
  }
  
  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;

  void writeCount(AllocSignal sig, uint64_t count) {
    const auto MAX_BUFSIZE = 1024;
    char buf[MAX_BUFSIZE];
    if (_pythonCount == 0) {
      _pythonCount = 1; // prevent 0/0
    }
#if 0
    stprintf::stprintf(_mmap + _lastpos,
		       "@,@,@,@\n\n",
		       ((sig == MallocSignal) ? 'M' : 'F'),
		       _mallocTriggered + _freeTriggered,
		       count,
		       (float) _pythonCount / (_pythonCount + _cCount));
#else
    //    tprintf::tprintf("count = @\n", count);
    snprintf(_mmap + _lastpos,
	     MAX_BUFSIZE,
#if defined(__APPLE__)
	     "%c,%llu,%llu,%f\n\n",
#else
	     "%c,%lu,%lu,%f\n\n",
#endif
	     ((sig == MallocSignal) ? 'M' : 'F'),
	     _mallocTriggered + _freeTriggered,
	     count,
	     (float) _pythonCount / (_pythonCount + _cCount));
#endif
    _lastpos += strlen(_mmap + _lastpos) - 1;
  }

};

#endif
