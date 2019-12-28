#ifndef STACK_HPP
#define STACK_HPP

#include "dynarray.hpp"
#include <cstring>

template <typename TYPE,
	  unsigned long BatchSize = 8>
class Stack {
public:
  Stack() : _index (0) {}

#if 0
  void mass_push(const TYPE v[BatchSize]) {
    std::memcpy(&_buf[_index], v, sizeof(TYPE) * BatchSize);
    _index += BatchSize;
  }
  
  void mass_pop(TYPE v[BatchSize]) {
    if (_index >= BatchSize) {
      _index -= BatchSize;
      std::memcpy(v, &_buf[_index], sizeof(TYPE) * BatchSize);
    } // Note: we fail silently if there are too few things on the stack.
  }
#endif
  
  inline void push(const TYPE v) {
    _buf[_index] = v;
    _index++;
  }

  inline auto size() const {
    return _index;
  }
  
  inline bool pop(TYPE& v) {
    if (likely(_index > 0)) {
      _index--;
      v = _buf[_index];
      return true;
    } else {
      return false;
    }
  }
  
private:
  unsigned long _index;
  DynArray<TYPE> _buf;
};


#endif
