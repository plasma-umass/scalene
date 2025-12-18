/**
 * @file libscalene_windows.cpp
 * @brief Windows-specific memory tracking for Scalene profiler
 *
 * This file implements memory allocation interposition on Windows.
 * Unlike Linux (LD_PRELOAD) and macOS (DYLD_INSERT_LIBRARIES), Windows
 * uses Python's allocator API to intercept allocations.
 */

#if defined(_WIN32)

#define SCALENE_DISABLE_SIGNALS 0  // Not applicable on Windows; we use Events

// SCALENE_LIBSCALENE_BUILD is defined via CMake to export symbols from this DLL

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

#include <windows.h>

// Microsoft Detours MUST be included after windows.h but before stdio.h
// _CRT_STDIO_ARBITRARY_WIDE_SPECIFIERS is defined in CMakeLists.txt
#include "detours.h"

#include <stdio.h>
#include <stdlib.h>
#include <cstddef>
#include <cstdint>
#include <malloc.h>
#include <new>
#include <atomic>
#include <string>
#include <unordered_map>

// Minimal definitions needed - avoid full heaplayers.h due to POSIX dependencies
#include "common_win.hpp"
#include "pywhere.hpp"
#include "samplefile_win.hpp"
#include "printf.h"  // Use malloc-safe printf functions

// Define the global variables declared (extern) in pywhere.hpp
// The extern "C" in pywhere.hpp with std::atomic is technically invalid but works
// because we're just exporting a symbol name, not using C calling convention on the type.
std::atomic<decltype(whereInPython)*> p_whereInPython{nullptr};
std::atomic<bool> p_scalene_done{true};

// Flag to coordinate between Python allocator and native malloc hooks
// When true, we're inside a Python allocator call - skip native hook tracking
// to avoid double-counting
static bool g_in_python_allocator = false;

// Flag to indicate if native hooks are installed
static bool g_native_hooks_installed = false;

// Export C-linkage accessor functions for Windows DLL symbol lookup
// since GetProcAddress can't find C++ mangled names
extern "C" ATTRIBUTE_EXPORT void* get_p_whereInPython() {
    return &p_whereInPython;
}

extern "C" ATTRIBUTE_EXPORT void* get_p_scalene_done() {
    return &p_scalene_done;
}

// For use by the replacement printf routines (if needed)
extern "C" void _putchar(char ch) {
  DWORD written;
  WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), &ch, 1, &written, NULL);
}

// Sampling parameters
constexpr uint64_t DefaultAllocationSamplingRate = 1 * 10485767ULL;
constexpr uint64_t MemcpySamplingRate = DefaultAllocationSamplingRate * 7;

// Windows Events for signaling (instead of Unix signals)
static HANDLE g_mallocEvent = NULL;
static HANDLE g_freeEvent = NULL;
static HANDLE g_memcpyEvent = NULL;

HANDLE getMallocEvent() {
  if (!g_mallocEvent) {
    g_mallocEvent = CreateEventA(NULL, FALSE, FALSE, "ScaleneMallocEvent");
  }
  return g_mallocEvent;
}

HANDLE getFreeEvent() {
  if (!g_freeEvent) {
    g_freeEvent = CreateEventA(NULL, FALSE, FALSE, "ScaleneFreeEvent");
  }
  return g_freeEvent;
}

HANDLE getMemcpyEvent() {
  if (!g_memcpyEvent) {
    g_memcpyEvent = CreateEventA(NULL, FALSE, FALSE, "ScaleneMemcpyEvent");
  }
  return g_memcpyEvent;
}

// Threshold-based sampler for Windows - matches Unix ThresholdSampler behavior
// Returns the accumulated count when threshold is crossed, not just true/false
class WindowsSampler {
public:
  WindowsSampler(uint64_t threshold)
    : _threshold(threshold), _increments(0), _decrements(0) {}

  // Increment (for mallocs) - returns true and accumulated net size when threshold crossed
  bool increment(size_t sz, size_t& ret) {
    _increments += sz;
    if (_increments >= _decrements + _threshold) {
      ret = _increments - _decrements;
      reset();
      return true;
    }
    return false;
  }

  // Decrement (for frees) - returns true and accumulated net size when threshold crossed
  bool decrement(size_t sz, size_t& ret) {
    _decrements += sz;
    if (_decrements >= _increments + _threshold) {
      ret = _decrements - _increments;
      reset();
      return true;
    }
    return false;
  }

  // Simple sample (for memcpy where we don't track free) - just uses increment
  bool sample(size_t sz) {
    size_t dummy;
    return increment(sz, dummy);
  }

private:
  void reset() {
    _increments = 0;
    _decrements = 0;
  }

  uint64_t _threshold;
  uint64_t _increments;
  uint64_t _decrements;
};

// Sampler instances
// Note: Using static instead of thread_local to avoid Windows DLL issues
// with dynamic loading. Since Python uses the GIL, this is acceptable.
static WindowsSampler mallocSampler(DefaultAllocationSamplingRate);
static WindowsSampler memcpySampler(MemcpySamplingRate);

// Get the sample files for communication with Python
static SampleFile& getMallocSampleFile() {
  static SampleFile sf("/tmp/scalene-malloc-signal%d",
                       "/tmp/scalene-malloc-lock%d",
                       "/tmp/scalene-malloc-init%d");
  return sf;
}

static SampleFile& getMemcpySampleFile() {
  static SampleFile sf("/tmp/scalene-memcpy-signal%d",
                       "/tmp/scalene-memcpy-lock%d",
                       "/tmp/scalene-memcpy-init%d");
  return sf;
}

// Simple heap wrapper that tracks allocations
static int g_malloc_call_count = 0;
static int g_malloc_sample_count = 0;
static int g_malloc_logged_count = 0;

// Debug counters for allocation hooks
static std::atomic<int> g_debug_malloc_count{0};
static std::atomic<int> g_debug_aligned_malloc_count{0};
static std::atomic<size_t> g_debug_largest_malloc{0};
static std::atomic<size_t> g_debug_largest_aligned{0};

// Counters to match Unix sampleheap.hpp format
static std::atomic<uint64_t> g_mallocTriggered{0};
static std::atomic<uint64_t> g_freeTriggered{0};

// Per-thread counters for Python vs C allocation tracking
// Note: We use simple static variables instead of thread_local because
// thread_local in Windows DLLs can cause crashes with dynamic loading.
// Since Python uses the GIL for most operations, this is acceptable.
static uint64_t g_pythonCount = 0;
static uint64_t g_cCount = 0;

// Track the last malloc trigger for freed-last-trigger detection
static void* g_lastMallocTrigger = nullptr;
static bool g_freedLastMallocTrigger = false;

class TheHeapWrapper {
public:
  static void register_malloc(size_t sz, void* ptr, bool inPythonAllocator = true) {
    g_malloc_call_count++;
    if (p_scalene_done) return;

    // Track Python vs C counts (accumulated since last sample)
    if (inPythonAllocator) {
      g_pythonCount += sz;
    } else {
      g_cCount += sz;
    }

    // Use increment() which returns the accumulated count when threshold is crossed
    size_t sampleSize = 0;
    if (mallocSampler.increment(sz, sampleSize)) {
      g_malloc_sample_count++;
      // Record the allocation with accumulated sample size
      auto& sf = getMallocSampleFile();
      if (p_whereInPython) {
        std::string filename;
        int lineno = 0, bytei = 0;
        if ((*p_whereInPython)(filename, lineno, bytei)) {
          g_malloc_logged_count++;

          // Prevent division by zero
          if (g_pythonCount == 0) {
            g_pythonCount = 1;
          }
          float python_fraction = (float)g_pythonCount / (g_pythonCount + g_cCount);

          char buf[SampleFile::MAX_BUFSIZE];
          // Format must match Unix sampleheap.hpp:
          // action,alloc_time,count,python_fraction,pid,pointer,filename,lineno,bytei\n
          // Note: Use sampleSize (accumulated) not sz (individual allocation)
          snprintf(buf, sizeof(buf), "M,%llu,%zu,%f,%d,%p,%s,%d,%d\n",
                   (unsigned long long)(g_mallocTriggered + g_freeTriggered),
                   sampleSize,
                   python_fraction,
                   _getpid(),
                   ptr,
                   filename.c_str(),
                   lineno,
                   bytei);
          sf.writeToFile(buf);

          // Update state after successful log
          g_lastMallocTrigger = ptr;
          g_freedLastMallocTrigger = false;
          g_pythonCount = 0;
          g_cCount = 0;
          g_mallocTriggered++;
        }
      }
      // Signal that we have data
      HANDLE hEvent = getMallocEvent();
      if (hEvent) SetEvent(hEvent);
    }
  }

  static void register_free(size_t sz, void* ptr) {
    if (p_scalene_done) return;

    // Check if we're freeing the last malloc trigger
    if (ptr && ptr == g_lastMallocTrigger) {
      g_freedLastMallocTrigger = true;
    }

    // Use decrement() which returns the accumulated count when threshold is crossed
    size_t sampleSize = 0;
    if (mallocSampler.decrement(sz, sampleSize)) {
      auto& sf = getMallocSampleFile();
      if (p_whereInPython) {
        std::string filename;
        int lineno = 0, bytei = 0;
        if ((*p_whereInPython)(filename, lineno, bytei)) {
          // Prevent division by zero
          if (g_pythonCount == 0) {
            g_pythonCount = 1;
          }
          float python_fraction = (float)g_pythonCount / (g_pythonCount + g_cCount);

          // Use 'f' if we freed the last malloc trigger, otherwise 'F'
          char action = g_freedLastMallocTrigger ? 'f' : 'F';
          void* reported_ptr = g_freedLastMallocTrigger ? g_lastMallocTrigger : ptr;

          char buf[SampleFile::MAX_BUFSIZE];
          // Format must match Unix sampleheap.hpp
          // Note: Use sampleSize (accumulated) not sz (individual free)
          snprintf(buf, sizeof(buf), "%c,%llu,%zu,%f,%d,%p,%s,%d,%d\n",
                   action,
                   (unsigned long long)(g_mallocTriggered + g_freeTriggered),
                   sampleSize,
                   python_fraction,
                   _getpid(),
                   reported_ptr,
                   filename.c_str(),
                   lineno,
                   bytei);
          sf.writeToFile(buf);

          // Clear the freed-last-trigger flag
          g_freedLastMallocTrigger = false;
          g_freeTriggered++;
        }
      }
      HANDLE hEvent = getFreeEvent();
      if (hEvent) SetEvent(hEvent);
    }
  }
};

// Memcpy sampler
// Counters to match Unix memcpysampler.hpp format
static std::atomic<uint64_t> g_memcpyTriggered{0};
// Note: Using static instead of thread_local to avoid Windows DLL issues
static uint64_t g_memcpyOps = 0;

class MemcpySamplerImpl {
private:
  void writeMemcpyCount(const std::string& filename, int lineno, int bytei) {
    auto& sf = getMemcpySampleFile();
    char buf[SampleFile::MAX_BUFSIZE];
    // Format must match Unix memcpysampler.hpp:
    // memcpy_time,count,pid,filename,lineno,bytei\n
    snprintf(buf, sizeof(buf), "%llu,%llu,%d,%s,%d,%d\n",
             (unsigned long long)g_memcpyTriggered,
             (unsigned long long)g_memcpyOps,
             _getpid(),
             filename.c_str(),
             lineno,
             bytei);
    sf.writeToFile(buf);
    g_memcpyTriggered++;
    g_memcpyOps = 0;
  }

public:
  void* memcpy(void* dst, const void* src, size_t n) {
    if (!p_scalene_done) {
      g_memcpyOps += n;
      if (memcpySampler.sample(n)) {
        // Record memcpy
        if (p_whereInPython) {
          std::string filename;
          int lineno = 0, bytei = 0;
          if ((*p_whereInPython)(filename, lineno, bytei)) {
            writeMemcpyCount(filename, lineno, bytei);
          }
        }
        HANDLE hEvent = getMemcpyEvent();
        if (hEvent) SetEvent(hEvent);
      }
    }
    return ::memcpy(dst, src, n);
  }

  void* memmove(void* dst, const void* src, size_t n) {
    if (!p_scalene_done) {
      g_memcpyOps += n;
      if (memcpySampler.sample(n)) {
        if (p_whereInPython) {
          std::string filename;
          int lineno = 0, bytei = 0;
          if ((*p_whereInPython)(filename, lineno, bytei)) {
            writeMemcpyCount(filename, lineno, bytei);
          }
        }
      }
    }
    return ::memmove(dst, src, n);
  }

  char* strcpy(char* dst, const char* src) {
    size_t n = strlen(src) + 1;
    if (!p_scalene_done) {
      g_memcpyOps += n;
      if (memcpySampler.sample(n)) {
        if (p_whereInPython) {
          std::string filename;
          int lineno = 0, bytei = 0;
          if ((*p_whereInPython)(filename, lineno, bytei)) {
            writeMemcpyCount(filename, lineno, bytei);
          }
        }
      }
    }
    return ::strcpy(dst, src);
  }
};

static MemcpySamplerImpl& getSampler() {
  static MemcpySamplerImpl sampler;
  return sampler;
}

// Export memcpy/memmove/strcpy wrappers
extern "C" ATTRIBUTE_EXPORT void* scalene_memcpy(void* dst, const void* src, size_t n) {
  return getSampler().memcpy(dst, src, n);
}

extern "C" ATTRIBUTE_EXPORT void* scalene_memmove(void* dst, const void* src, size_t n) {
  return getSampler().memmove(dst, src, n);
}

extern "C" ATTRIBUTE_EXPORT char* scalene_strcpy(char* dst, const char* src) {
  return getSampler().strcpy(dst, src);
}

//=============================================================================
// Native malloc/free hooks using Microsoft Detours
// These intercept ALL malloc/free calls, including from native libraries like numpy
//=============================================================================

// Original function pointers (trampolines) - Detours will fill these in
static void* (__cdecl *Real_malloc)(size_t) = malloc;
static void (__cdecl *Real_free)(void*) = free;
static void* (__cdecl *Real_realloc)(void*, size_t) = realloc;
static void* (__cdecl *Real_calloc)(size_t, size_t) = calloc;
static void* (__cdecl *Real_aligned_malloc)(size_t, size_t) = _aligned_malloc;
static void (__cdecl *Real_aligned_free)(void*) = _aligned_free;
static void* (__cdecl *Real_aligned_realloc)(void*, size_t, size_t) = _aligned_realloc;

// Flag to prevent recursive hooking during hook execution
static bool g_in_native_hook = false;

// Native allocation size tracking
// We can't rely on _msize() because it fails for custom allocators (numpy, etc.)
static std::unordered_map<void*, size_t> g_native_alloc_sizes;
static CRITICAL_SECTION g_native_alloc_sizes_lock;
static bool g_native_alloc_tracking_initialized = false;

static void init_native_alloc_tracking() {
    if (!g_native_alloc_tracking_initialized) {
        InitializeCriticalSection(&g_native_alloc_sizes_lock);
        g_native_alloc_tracking_initialized = true;
    }
}

static void track_native_alloc(void* ptr, size_t size) {
    if (!ptr || !g_native_alloc_tracking_initialized) return;
    EnterCriticalSection(&g_native_alloc_sizes_lock);
    g_native_alloc_sizes[ptr] = size;
    LeaveCriticalSection(&g_native_alloc_sizes_lock);
}

static size_t untrack_native_alloc(void* ptr) {
    if (!ptr || !g_native_alloc_tracking_initialized) return 0;
    size_t size = 0;
    EnterCriticalSection(&g_native_alloc_sizes_lock);
    auto it = g_native_alloc_sizes.find(ptr);
    if (it != g_native_alloc_sizes.end()) {
        size = it->second;
        g_native_alloc_sizes.erase(it);
    }
    LeaveCriticalSection(&g_native_alloc_sizes_lock);
    return size;
}

// Hooked malloc - intercepts ALL malloc calls from any code
static void* __cdecl Hooked_malloc(size_t size) {
    // Check recursion guard FIRST - track_native_alloc may call malloc internally
    if (g_in_native_hook || g_in_python_allocator) {
        return Real_malloc(size);
    }

    g_in_native_hook = true;
    void* ptr = Real_malloc(size);
    if (ptr) {
        g_debug_malloc_count++;
        if (size > g_debug_largest_malloc) {
            g_debug_largest_malloc = size;
        }
        // Track the allocation size for later free
        track_native_alloc(ptr, size);
        if (!p_scalene_done) {
            TheHeapWrapper::register_malloc(size, ptr, false);  // false = native allocation
        }
    }
    g_in_native_hook = false;
    return ptr;
}

// Hooked free - intercepts ALL free calls
static void __cdecl Hooked_free(void* ptr) {
    // Check recursion guard FIRST
    if (g_in_native_hook || g_in_python_allocator) {
        Real_free(ptr);
        return;
    }

    if (ptr) {
        g_in_native_hook = true;
        // Look up size from our tracking (don't rely on _msize)
        size_t size = untrack_native_alloc(ptr);
        if (!p_scalene_done && size > 0) {
            TheHeapWrapper::register_free(size, ptr);
        }
        g_in_native_hook = false;
    }
    Real_free(ptr);
}

// Hooked realloc - intercepts ALL realloc calls
static void* __cdecl Hooked_realloc(void* ptr, size_t size) {
    // Check recursion guard FIRST
    if (g_in_native_hook || g_in_python_allocator) {
        return Real_realloc(ptr, size);
    }

    g_in_native_hook = true;
    size_t old_size = 0;
    if (ptr) {
        // Look up old size from our tracking
        old_size = untrack_native_alloc(ptr);
    }

    void* new_ptr = Real_realloc(ptr, size);

    if (new_ptr) {
        // Track the new allocation
        track_native_alloc(new_ptr, size);
        if (!p_scalene_done) {
            if (size > old_size) {
                TheHeapWrapper::register_malloc(size - old_size, new_ptr, false);
            } else if (old_size > size) {
                TheHeapWrapper::register_free(old_size - size, new_ptr);
            }
        }
    }
    g_in_native_hook = false;
    return new_ptr;
}

// Hooked calloc - intercepts ALL calloc calls
static void* __cdecl Hooked_calloc(size_t num, size_t size) {
    // Check recursion guard FIRST
    if (g_in_native_hook || g_in_python_allocator) {
        return Real_calloc(num, size);
    }

    g_in_native_hook = true;
    void* ptr = Real_calloc(num, size);
    if (ptr) {
        size_t total = num * size;
        // Track the allocation size
        track_native_alloc(ptr, total);
        if (!p_scalene_done) {
            TheHeapWrapper::register_malloc(total, ptr, false);
        }
    }
    g_in_native_hook = false;
    return ptr;
}

// Hooked _aligned_malloc - intercepts aligned allocations (used by numpy for large arrays)
static void* __cdecl Hooked_aligned_malloc(size_t size, size_t alignment) {
    // Check recursion guard FIRST
    if (g_in_native_hook || g_in_python_allocator) {
        return Real_aligned_malloc(size, alignment);
    }

    g_in_native_hook = true;
    void* ptr = Real_aligned_malloc(size, alignment);
    if (ptr) {
        g_debug_aligned_malloc_count++;
        if (size > g_debug_largest_aligned) {
            g_debug_largest_aligned = size;
        }
        track_native_alloc(ptr, size);
        if (!p_scalene_done) {
            TheHeapWrapper::register_malloc(size, ptr, false);
        }
    }
    g_in_native_hook = false;
    return ptr;
}

// Hooked _aligned_free - intercepts aligned frees
static void __cdecl Hooked_aligned_free(void* ptr) {
    // Check recursion guard FIRST
    if (g_in_native_hook || g_in_python_allocator) {
        Real_aligned_free(ptr);
        return;
    }

    if (ptr) {
        g_in_native_hook = true;
        size_t size = untrack_native_alloc(ptr);
        if (!p_scalene_done && size > 0) {
            TheHeapWrapper::register_free(size, ptr);
        }
        g_in_native_hook = false;
    }
    Real_aligned_free(ptr);
}

// Hooked _aligned_realloc - intercepts aligned reallocs
static void* __cdecl Hooked_aligned_realloc(void* ptr, size_t size, size_t alignment) {
    // Check recursion guard FIRST
    if (g_in_native_hook || g_in_python_allocator) {
        return Real_aligned_realloc(ptr, size, alignment);
    }

    g_in_native_hook = true;
    size_t old_size = 0;
    if (ptr) {
        old_size = untrack_native_alloc(ptr);
    }

    void* new_ptr = Real_aligned_realloc(ptr, size, alignment);

    if (new_ptr) {
        track_native_alloc(new_ptr, size);
        if (!p_scalene_done) {
            if (size > old_size) {
                TheHeapWrapper::register_malloc(size - old_size, new_ptr, false);
            } else if (old_size > size) {
                TheHeapWrapper::register_free(old_size - size, new_ptr);
            }
        }
    }
    g_in_native_hook = false;
    return new_ptr;
}

// Install native malloc/free hooks using Detours
static bool install_native_hooks() {
    if (g_native_hooks_installed) {
        return true;
    }

    // Initialize native allocation tracking
    init_native_alloc_tracking();

    DetourRestoreAfterWith();

    LONG error = DetourTransactionBegin();
    if (error != NO_ERROR) {
        return false;
    }

    error = DetourUpdateThread(GetCurrentThread());
    if (error != NO_ERROR) {
        DetourTransactionAbort();
        return false;
    }

    // Attach our hooks
    DetourAttach(&(PVOID&)Real_malloc, Hooked_malloc);
    DetourAttach(&(PVOID&)Real_free, Hooked_free);
    DetourAttach(&(PVOID&)Real_realloc, Hooked_realloc);
    DetourAttach(&(PVOID&)Real_calloc, Hooked_calloc);
    DetourAttach(&(PVOID&)Real_aligned_malloc, Hooked_aligned_malloc);
    DetourAttach(&(PVOID&)Real_aligned_free, Hooked_aligned_free);
    DetourAttach(&(PVOID&)Real_aligned_realloc, Hooked_aligned_realloc);

    error = DetourTransactionCommit();
    if (error == NO_ERROR) {
        g_native_hooks_installed = true;
        return true;
    }
    return false;
}

// Uninstall native hooks (called during cleanup)
static void uninstall_native_hooks() {
    if (!g_native_hooks_installed) {
        return;
    }

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    DetourDetach(&(PVOID&)Real_malloc, Hooked_malloc);
    DetourDetach(&(PVOID&)Real_free, Hooked_free);
    DetourDetach(&(PVOID&)Real_realloc, Hooked_realloc);
    DetourDetach(&(PVOID&)Real_calloc, Hooked_calloc);
    DetourDetach(&(PVOID&)Real_aligned_malloc, Hooked_aligned_malloc);
    DetourDetach(&(PVOID&)Real_aligned_free, Hooked_aligned_free);
    DetourDetach(&(PVOID&)Real_aligned_realloc, Hooked_aligned_realloc);

    DetourTransactionCommit();
    g_native_hooks_installed = false;
}

//=============================================================================
// Python allocator interception
//=============================================================================
#include <Python.h>

// Simple recursion guard using static variable
// Note: Using static instead of thread_local to avoid Windows DLL issues
// with dynamic loading. Since Python uses the GIL, this is acceptable.
static bool inMalloc = false;

class MallocRecursionGuard {
public:
  MallocRecursionGuard() : wasInMalloc_(inMalloc) {
    inMalloc = true;
  }
  ~MallocRecursionGuard() {
    inMalloc = wasInMalloc_;
  }
  bool wasInMalloc() const { return wasInMalloc_; }
private:
  bool wasInMalloc_;
};

/**
 * @brief Python allocator interception - deferred initialization
 *
 * We can't install hooks at static init time because Python may not be ready.
 * Instead, we provide functions to install/uninstall hooks on demand.
 */

// Storage for original allocators
static PyMemAllocatorEx g_original_mem_allocator;
static PyMemAllocatorEx g_original_obj_allocator;
static PyMemAllocatorEx g_scalene_mem_allocator;
static PyMemAllocatorEx g_scalene_obj_allocator;
static bool g_allocators_installed = false;

// Track allocation sizes for proper free accounting
// Use a simple hash map with mutex for thread safety
#include <unordered_map>
static std::unordered_map<void*, size_t> g_alloc_sizes;
static CRITICAL_SECTION g_alloc_sizes_lock;
static bool g_alloc_sizes_initialized = false;

static void init_alloc_tracking() {
    if (!g_alloc_sizes_initialized) {
        InitializeCriticalSection(&g_alloc_sizes_lock);
        g_alloc_sizes_initialized = true;
    }
}

static void track_alloc(void* ptr, size_t size) {
    if (!ptr) return;
    EnterCriticalSection(&g_alloc_sizes_lock);
    g_alloc_sizes[ptr] = size;
    LeaveCriticalSection(&g_alloc_sizes_lock);
}

static size_t untrack_alloc(void* ptr) {
    if (!ptr) return 0;
    size_t size = 0;
    EnterCriticalSection(&g_alloc_sizes_lock);
    auto it = g_alloc_sizes.find(ptr);
    if (it != g_alloc_sizes.end()) {
        size = it->second;
        g_alloc_sizes.erase(it);
    }
    LeaveCriticalSection(&g_alloc_sizes_lock);
    return size;
}

// Forward declarations for allocator functions
static void* scalene_malloc(void* ctx, size_t len);
static void* scalene_calloc(void* ctx, size_t nelem, size_t elsize);
static void* scalene_realloc(void* ctx, void* ptr, size_t new_size);
static void scalene_free(void* ctx, void* ptr);

// Function pointers for Python allocator API
typedef void (*GetAllocatorFunc)(PyMemAllocatorDomain, PyMemAllocatorEx*);
typedef void (*SetAllocatorFunc)(PyMemAllocatorDomain, PyMemAllocatorEx*);
static GetAllocatorFunc g_PyMem_GetAllocator = nullptr;
static SetAllocatorFunc g_PyMem_SetAllocator = nullptr;

static bool find_python_allocator_api() {
    if (g_PyMem_GetAllocator && g_PyMem_SetAllocator) {
        return true;
    }

    // Try common Python DLL names
    const char* dllNames[] = {
        "python3.dll",
        "python314.dll",
        "python313.dll",
        "python312.dll",
        "python311.dll",
        "python310.dll",
        "python39.dll",
        "python38.dll",
        nullptr
    };

    for (const char** name = dllNames; *name; ++name) {
        HMODULE hPython = GetModuleHandleA(*name);
        if (hPython) {
            g_PyMem_GetAllocator = (GetAllocatorFunc)GetProcAddress(
                hPython, "PyMem_GetAllocator");
            g_PyMem_SetAllocator = (SetAllocatorFunc)GetProcAddress(
                hPython, "PyMem_SetAllocator");
            if (g_PyMem_GetAllocator && g_PyMem_SetAllocator) {
                return true;
            }
        }
    }
    return false;
}

// Allocator functions with size tracking
// These set g_in_python_allocator to prevent native hooks from double-counting
static void* scalene_malloc(void* ctx, size_t len) {
    // Safety check - ensure original allocator is valid
    if (!g_original_mem_allocator.malloc) {
        return nullptr;
    }
    g_in_python_allocator = true;  // Prevent native hooks from tracking
    MallocRecursionGuard m;
    void* ptr = g_original_mem_allocator.malloc(g_original_mem_allocator.ctx, len);
    if (ptr) {
        track_alloc(ptr, len);
        if (!m.wasInMalloc()) {
            TheHeapWrapper::register_malloc(len, ptr, true);  // true = Python allocation
        }
    }
    g_in_python_allocator = false;
    return ptr;
}

static void scalene_free(void* ctx, void* ptr) {
    if (ptr) {
        // Safety check - ensure original allocator is valid
        if (!g_original_mem_allocator.free) {
            return;
        }
        g_in_python_allocator = true;  // Prevent native hooks from tracking
        MallocRecursionGuard m;
        size_t sz = untrack_alloc(ptr);
        if (!m.wasInMalloc() && sz > 0) {
            TheHeapWrapper::register_free(sz, ptr);
        }
        g_original_mem_allocator.free(g_original_mem_allocator.ctx, ptr);
        g_in_python_allocator = false;
    }
}

static void* scalene_realloc(void* ctx, void* ptr, size_t new_size) {
    if (!ptr) {
        return scalene_malloc(ctx, new_size);
    }
    // Safety check - ensure original allocator is valid
    if (!g_original_mem_allocator.realloc) {
        return nullptr;
    }
    g_in_python_allocator = true;  // Prevent native hooks from tracking
    MallocRecursionGuard m;
    size_t old_size = untrack_alloc(ptr);
    void* new_ptr = g_original_mem_allocator.realloc(
        g_original_mem_allocator.ctx, ptr, new_size);
    if (new_ptr) {
        track_alloc(new_ptr, new_size);
        if (!m.wasInMalloc()) {
            if (new_size > old_size) {
                TheHeapWrapper::register_malloc(new_size - old_size, new_ptr, true);
            } else if (old_size > new_size) {
                TheHeapWrapper::register_free(old_size - new_size, new_ptr);
            }
        }
    }
    g_in_python_allocator = false;
    return new_ptr;
}

static void* scalene_calloc(void* ctx, size_t nelem, size_t elsize) {
    // Safety check - ensure original allocator is valid
    if (!g_original_mem_allocator.calloc) {
        return nullptr;
    }
    g_in_python_allocator = true;  // Prevent native hooks from tracking
    MallocRecursionGuard m;
    size_t total = nelem * elsize;
    void* ptr = g_original_mem_allocator.calloc(g_original_mem_allocator.ctx, nelem, elsize);
    if (ptr) {
        track_alloc(ptr, total);
        if (!m.wasInMalloc()) {
            TheHeapWrapper::register_malloc(total, ptr, true);  // true = Python allocation
        }
    }
    g_in_python_allocator = false;
    return ptr;
}

static bool install_allocator_hooks() {
    if (g_allocators_installed) {
        return true;
    }

    if (!find_python_allocator_api()) {
        return false;
    }

    // Initialize allocation tracking
    init_alloc_tracking();

    // Set up our allocator structure
    g_scalene_mem_allocator.ctx = nullptr;
    g_scalene_mem_allocator.malloc = scalene_malloc;
    g_scalene_mem_allocator.calloc = scalene_calloc;
    g_scalene_mem_allocator.realloc = scalene_realloc;
    g_scalene_mem_allocator.free = scalene_free;

    g_scalene_obj_allocator = g_scalene_mem_allocator;

    // Save original allocators and install ours
    g_PyMem_GetAllocator(PYMEM_DOMAIN_MEM, &g_original_mem_allocator);
    g_PyMem_GetAllocator(PYMEM_DOMAIN_OBJ, &g_original_obj_allocator);

    g_PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &g_scalene_mem_allocator);
    g_PyMem_SetAllocator(PYMEM_DOMAIN_OBJ, &g_scalene_obj_allocator);

    g_allocators_installed = true;
    return true;
}

// DLL entry point for initialization
extern "C" BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason,
                               LPVOID lpvReserved) {
  switch (fdwReason) {
    case DLL_PROCESS_ATTACH:
      DisableThreadLibraryCalls(hinstDLL);
      break;
    case DLL_PROCESS_DETACH:
      // Uninstall native hooks before DLL unload
      uninstall_native_hooks();
      if (g_mallocEvent) CloseHandle(g_mallocEvent);
      if (g_freeEvent) CloseHandle(g_freeEvent);
      if (g_memcpyEvent) CloseHandle(g_memcpyEvent);
      break;
  }
  return TRUE;
}

// Export function to initialize the profiler from Python
extern "C" ATTRIBUTE_EXPORT void scalene_init() {
  getMallocSampleFile();
  getMemcpySampleFile();
  getSampler();
  install_allocator_hooks();
  // Install native malloc/free hooks using Detours
  // This intercepts ALL malloc/free calls, including from native libraries
  install_native_hooks();
}

// Debug function to dump stats
extern "C" ATTRIBUTE_EXPORT void scalene_dump_stats() {
  printf("=== Scalene Debug Stats ===\n");
  printf("  malloc calls: %d (largest: %zu bytes = %.2f MB)\n",
         g_debug_malloc_count.load(), g_debug_largest_malloc.load(),
         g_debug_largest_malloc.load() / (1024.0 * 1024.0));
  printf("  aligned_malloc calls: %d (largest: %zu bytes = %.2f MB)\n",
         g_debug_aligned_malloc_count.load(), g_debug_largest_aligned.load(),
         g_debug_largest_aligned.load() / (1024.0 * 1024.0));
  printf("  malloc samples: %d, logged: %d\n", g_malloc_sample_count, g_malloc_logged_count);
  printf("  mallocTriggered: %llu, freeTriggered: %llu\n",
         (unsigned long long)g_mallocTriggered.load(),
         (unsigned long long)g_freeTriggered.load());
  printf("===========================\n");
}

// Export function to set the whereInPython callback
extern "C" ATTRIBUTE_EXPORT void scalene_set_where_in_python(
    decltype(whereInPython)* func) {
  p_whereInPython = func;
}

// Export function to signal profiling is done
extern "C" ATTRIBUTE_EXPORT void scalene_set_done(bool done) {
  p_scalene_done = done;
}

#endif // _WIN32
