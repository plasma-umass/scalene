#ifndef SAMPLEHEAP_H
#define SAMPLEHEAP_H

#include <signal.h>

template <class SuperHeap, unsigned long Start = 10485760, unsigned long Bytes = 128 * 1024>
class SampleHeap : public SuperHeap {
public:

  SampleHeap()
    : _timer (Start),
      _signalsEnabled (false)
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
    if (sz >= _timer) {
      if (_signalsEnabled) {
	// Raise a signal.
	//	tprintf::tprintf("freed memory = @\n", SuperHeap::freedMemory());
	raise(SIGVTALRM);
      } else {
	_signalsEnabled = true; // next time we will signal.
      }
      // Reset the counter.
      _timer = Bytes;
    } else {
      _timer -= sz;
    }
    return SuperHeap::malloc(sz);
  }
  
private:
  long _timer;
  bool _signalsEnabled;
};

#endif
