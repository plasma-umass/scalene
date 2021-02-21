#ifndef STPRINTF_H
#define STPRINTF_H

#pragma once

// Written by Emery Berger

#include <string.h>

#include <cmath>
#include <cstdint>

using namespace std;

namespace stprintf {

template <typename T>
inline int writeval(char *buf, T v, size_t sz);

template <typename T>
inline int itoa(char *buf, T v, size_t sz) {
  if (sz == 0) {
    return 0;
  }
  long n = (long)v;
  auto startbuf = buf;
  if (n < 0) {
    sz--;
    *buf++ = '-';
    n = -n;
  }
  if (n == 0) {
    if (sz) {
      sz--;
      *buf++ = '0';
    }
    return (int)(buf - startbuf);
  }
  long tens = 1L;
  while (n / (10 * tens)) {
    tens *= 10;
  }
  while (tens) {
    sz--;
    if (sz == 0) {
      break;
    }
    *buf++ = '0' + n / tens;
    n = n - (n / tens) * tens;
    tens /= 10;
  }
  return (int)(buf - startbuf);
}

inline int ftoa(char *buf, double n, size_t sz, int decimalPlaces = 8) {
  // Extract integer part
  auto ipart = (long)n;

  // Extract floating part
  auto fpart = n - (double)ipart;
  if (fpart < 0.0) {
    fpart = -fpart;
  }

  // convert integer part to string
  int i = itoa(buf, ipart, sz);

  if (decimalPlaces > 0) {
    buf[i] = '.';
    auto multiple = pow(10, decimalPlaces);
    fpart = fpart * multiple;
    multiple /= 10;
    while ((fpart < multiple) && (decimalPlaces > 0)) {
      if (sz == 0) {
        break;
      }
      buf[++i] = '0';
      sz--;
      multiple /= 10;
      decimalPlaces--;
    }
    if (fpart > 0) {
      i = i + itoa(buf + i + 1, (long)fpart, sz - (i + 1)) + 1;
    }
  }
  return i;
}

inline int writeval(char *buf, double n, size_t sz) {
  int len = ftoa(buf, n, sz);
  return len;
}

inline int writeval(char *buf, float n, size_t sz) {
  int len = ftoa(buf, n, sz);
  return len;
}

inline int writeval(char *buf, const char *str, size_t sz) {
  //    cout << "len = " << len << ", str = " << str << endl;
  int i = 0;
  for (; i < sz && str[i] != '\0'; i++) {
    buf[i] = str[i];
  }
  return i;
}

inline int writeval(char *buf, const char c, size_t sz) {
  if (sz >= 1) {
    buf[0] = c;
    return 1;
  } else {
    return 0;
  }
}

inline int writeval(char *buf, uint64_t n, size_t sz) {
  int len = itoa(buf, n, sz);
  return len;
}

template <class T>
inline int writeval(char *buf, T n, size_t sz) {
  int len = itoa(buf, n, sz);
  return len;
}

inline void stprintf(char *buf, const char *format, size_t sz)  // base function
{
  writeval(buf, format, sz);
}

template <typename T, typename... Targs>
inline void stprintf(char *buf, const char *format, size_t sz, T value,
                     Targs... Fargs) {
  // Limit the number of formats to the number of args.
  if (sz == 0) {
    return;
  }
  unsigned int formatStrCount = 0;
  for (; *format != '\0'; format++) {
    if (*format == '@') {
      if (*(format + 1) == '\\') {
        auto len = writeval(buf, "@", sz);
        buf += len;
        sz -= len;
        format = format + 2;
      } else {
        formatStrCount += 1;
        if (formatStrCount <= sizeof...(Fargs) + 1) {
          auto len = writeval(buf, value, sz);
          buf += len;
          sz -= len;
          stprintf(buf, format + 1, sz, Fargs...);
        }
        return;
      }
    }
    auto len = writeval(buf, *format, sz);
    buf += len;
    sz -= len;
#if 0
    // zero-terminate if there is room
    if (sz >= 1) {
      ++buf;
      *buf = '\0';
    }
#endif
  }
}

}  // namespace stprintf

#endif
