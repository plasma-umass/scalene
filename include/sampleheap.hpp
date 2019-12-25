#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <signal.h>

template <class SuperHeap, unsigned long Start = 10485760, unsigned long Bytes = 128 * 1024>
class SampleHeap : public SuperHeap {
public:

  SampleHeap()
    : _timer (Start),
      _signalsEnabled (false),
      _mallocs (0),
      _frees (0)
  {
    //    fprintf(stderr, "HELLO\n");
  }

  void enableSignals() {
    _signalsEnabled = true;
  }

  void disableSignals() {
    _signalsEnabled = false;
  }
  
  void * malloc(size_t sz) {
    if (!_signalsEnabled && (sz < _timer)) {
      _timer -= sz;
    } else {
      _signalsEnabled = true; // next time we will signal.
    }
    auto ptr = SuperHeap::malloc(sz);
    _mallocs += SuperHeap::getSize(ptr);
    if (_mallocs - _frees > Bytes) {
      if (_signalsEnabled) {
	// Raise a signal.
	//	tprintf::tprintf("freed memory = @\n", SuperHeap::freedMemory());
	raise(SIGVTALRM);
      }
      _mallocs = 0;
      _frees = 0;
    }
    return ptr;
  }

  void free(void * ptr) {
    auto sz = SuperHeap::getSize(ptr);
    _frees += sz;
    SuperHeap::free(ptr);
  }
  
private:
  long _timer;
  unsigned long _mallocs;
  unsigned long _frees;
  bool _signalsEnabled;
};

#endif
