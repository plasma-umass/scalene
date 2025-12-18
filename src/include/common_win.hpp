#pragma once

#ifndef COMMON_WIN_HPP
#define COMMON_WIN_HPP

#if defined(_WIN32)

// Windows-specific definitions for Scalene

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

// Likely/unlikely macros - MSVC doesn't have __builtin_expect
#ifndef likely
#if defined(_MSC_VER) && _MSC_VER >= 1900
// MSVC 2015+ has some branch prediction hints but not as good as GCC
#define likely(x) (x)
#define unlikely(x) (x)
#else
#define likely(x) (x)
#define unlikely(x) (x)
#endif
#endif

// Attribute macros for MSVC
#ifdef _MSC_VER
#define ATTRIBUTE_NEVER_INLINE __declspec(noinline)
#define ATTRIBUTE_ALWAYS_INLINE __forceinline
#define ATTRIBUTE_HIDDEN
#define ATTRIBUTE_EXPORT __declspec(dllexport)
#define ATTRIBUTE_ALIGNED(s) __declspec(align(s))
#else
// MinGW GCC on Windows
#define ATTRIBUTE_NEVER_INLINE __attribute__((noinline))
#define ATTRIBUTE_ALWAYS_INLINE __attribute__((always_inline))
#define ATTRIBUTE_HIDDEN __attribute__((visibility("hidden")))
#define ATTRIBUTE_EXPORT __declspec(dllexport)
#define ATTRIBUTE_ALIGNED(s) __attribute__((aligned(s)))
#endif

#define CACHELINE_SIZE 64
#define CACHELINE_ALIGNED ATTRIBUTE_ALIGNED(CACHELINE_SIZE)
#define CACHELINE_ALIGNED_FN CACHELINE_ALIGNED

#define USE_COMPRESSED_PTRS 0
#define USE_SIZE_CACHES 0

// Windows equivalents for POSIX functions
#include <process.h>  // for _getpid

#ifndef getpid
#define getpid _getpid
#endif

#endif // _WIN32

#endif // COMMON_WIN_HPP
