#ifndef CLASSWARFARE_H
#define CLASSWARFARE_H

template <unsigned long Multiple = 8>
class ClassWarfare {
public:
  inline static void getSizeAndClass(const size_t sz, size_t& rounded, unsigned long& sizeClass) {
    rounded = (sz + (Multiple - 1)) & ~(Multiple - 1);
    sizeClass = rounded / Multiple - 1;
  }

  inline static void getSizeFromClass(const unsigned long sizeClass, size_t& sz) {
    sz = (sizeClass + 1) * Multiple;
  }
};

#endif
