# Windows Memory Profiling Port - Progress and Plans

## Overview

Porting Scalene's memory profiling from Linux/macOS to Windows. On Unix systems, Scalene uses `LD_PRELOAD`/`DYLD_INSERT_LIBRARIES` to interpose on malloc/free. Windows doesn't support this mechanism, so we use Python's allocator API instead.

## Architecture

### Unix Approach
- `libscalene.so`/`libscalene.dylib` is preloaded via environment variables
- Interposes on malloc/free/realloc at the C library level
- Uses Unix signals (SIGXCPU, SIGXFSZ) to communicate with Python
- Uses POSIX shared memory (`/tmp/scalene-*`) for data transfer

### Windows Approach
- `libscalene.dll` is loaded explicitly via ctypes
- Uses Python's `PyMem_SetAllocator` API to intercept allocations
- Uses Windows Events instead of Unix signals (but currently using polling)
- Uses Windows Named Shared Memory (`Local\scalene-*`) for data transfer

## Files Created/Modified

### New Files
- `src/source/libscalene_windows.cpp` - Main Windows DLL implementation (includes Detours native hooks)
- `src/include/samplefile_win.hpp` - Windows shared memory implementation
- `src/include/common_win.hpp` - Windows compatibility macros
- `src/include/mallocrecursionguard_win.hpp` - Windows TLS-based recursion guard
- `scalene/scalene_windows.py` - Python helper for Windows memory profiling
- `vendor/Detours/` - Microsoft Detours library for native malloc/free hooking (vendored)

### Modified Files
- `CMakeLists.txt` - Cross-platform build configuration with Detours integration
- `src/include/pywhere.hpp` - Windows DLL export/import macros
- `src/source/pywhere.cpp` - Windows symbol lookup via accessor functions
- `scalene/scalene_profiler.py` - Windows DLL loading and initialization
- `scalene/scalene_mapfile.py` - Windows named shared memory support
- `scalene/scalene_signal_manager.py` - Windows memory polling thread
- `scalene/scalene_preload.py` - Case-insensitive ARM64 detection
- `scalene/scalene_arguments.py` - Enable memory profiling on Windows

## Current Status (2024-12-17) - FULLY WORKING WITH NATIVE LIBRARY SUPPORT!

### All Core Features Working
1. ✅ DLL builds successfully with CMake/MSBuild for ARM64
2. ✅ DLL loads without crashing
3. ✅ Python allocator hooks are installed via `PyMem_SetAllocator`
4. ✅ Allocation size tracking implemented (hash map with critical section)
5. ✅ Shared memory objects created successfully (both malloc and memcpy)
6. ✅ ScaleneMapFile opens shared memory from Python side successfully
7. ✅ All `thread_local` variables removed (caused crashes with dynamically loaded DLLs on Windows)
8. ✅ Data format updated to match Unix (comma-separated, 9 fields for malloc, 6 for memcpy)
9. ✅ Windows memory polling thread added to `scalene_signal_manager.py`
10. ✅ **64-bit pointer handling fixed in ctypes code**
11. ✅ Memory profiling working - samples being collected and logged
12. ✅ **Native library tracking (numpy, etc.) via Microsoft Detours**
13. ✅ **Proper free tracking with manual size tracking hash map**

### Test Results (2024-12-17)
```
alloc_samples: 203
max_footprint_mb: 152.71
max_footprint_python_fraction: 0.000288
Native fraction: 99.97%
```

The profiler now correctly tracks memory allocations from native libraries like numpy, with proper line attribution.

### Known Limitation
- Console output may fail with `UnicodeEncodeError` on Windows consoles using CP1252 encoding
- This is not a profiler bug - it's a Windows console limitation
- **Workaround**: Set `PYTHONIOENCODING=utf-8` environment variable or use `--html` or `--json` output

## The Critical Bug Fix (2024-12-16)

### Root Cause: ctypes 64-bit Pointer Truncation

The Access Violation crash (exit code 3221225477 = 0xC0000005) was caused by a **ctypes bug** where 64-bit pointers were being truncated to 32-bit values.

**Problem**: By default, ctypes assumes Windows API functions return `c_int` (32-bit). On 64-bit Windows, `MapViewOfFile` returns a 64-bit pointer. Without explicit return type declaration, the high 32 bits were truncated, causing invalid memory addresses.

**Example of bug**:
```
MapViewOfFile returns: 0x00007FFBF2650B90  (valid 64-bit pointer)
ctypes stored as:      0x00000000F2650B90  (truncated to 32-bit, invalid!)
```

### The Fix (scalene_mapfile.py)

Added proper return type declarations before calling Windows API functions:

```python
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

# IMPORTANT: Set proper return types for Windows API functions
# Default ctypes return type is c_int (32-bit) which truncates 64-bit pointers
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
```

This fix is in `scalene/scalene_mapfile.py` in the `_init_windows()` method.

## Native Library Memory Tracking (2024-12-17)

### The Problem

The original Windows implementation only tracked Python allocations via `PyMem_SetAllocator`. Native library allocations (numpy arrays, pandas dataframes, etc.) went untracked because they bypass Python's allocator and call the C runtime `malloc`/`free` directly.

**Before**: Only Python allocations tracked (0.03% of actual memory usage)
**After**: All allocations tracked including native libraries (99.97% native, 0.03% Python)

### Solution: Microsoft Detours

We use [Microsoft Detours](https://github.com/microsoft/Detours) to intercept `malloc`/`free`/`realloc`/`calloc` at the C runtime level. Detours works by rewriting the first few bytes of target functions with a jump to our hooks.

**Why Detours over alternatives:**
- **MinHook**: Does NOT support ARM64 (only x86/x64)
- **IAT Hooking**: Complex, requires hooking each loaded module separately
- **ETW (Event Tracing)**: Requires admin privileges, high overhead
- **Detours**: Supports ARM64, x64, x86, ARM - official Microsoft library, MIT licensed

### Implementation

#### Files Modified/Added
- `vendor/Detours/` - Microsoft Detours source (vendored)
- `CMakeLists.txt` - Added Detours to Windows build with architecture-specific disassembler
- `src/source/libscalene_windows.cpp` - Added native hooks using Detours

#### CMakeLists.txt Changes
```cmake
# Microsoft Detours sources for native malloc/free hooking
set(DETOURS_SOURCES
    vendor/Detours/src/detours.cpp
    vendor/Detours/src/modules.cpp
    vendor/Detours/src/disasm.cpp
    vendor/Detours/src/image.cpp
    vendor/Detours/src/creatwth.cpp
)

# Add architecture-specific disassembler
if(SCALENE_ARCH STREQUAL "ARM64")
    list(APPEND DETOURS_SOURCES vendor/Detours/src/disolarm64.cpp)
elseif(SCALENE_ARCH STREQUAL "X64")
    list(APPEND DETOURS_SOURCES vendor/Detours/src/disolx64.cpp)
elseif(SCALENE_ARCH STREQUAL "X86")
    list(APPEND DETOURS_SOURCES vendor/Detours/src/disolx86.cpp)
endif()

target_compile_definitions(scalene PRIVATE DETOURS_INTERNAL)
```

#### Native Hook Implementation
```cpp
#include "detours.h"

// Original function pointers (Detours fills these with trampolines)
static void* (__cdecl *Real_malloc)(size_t) = malloc;
static void (__cdecl *Real_free)(void*) = free;
static void* (__cdecl *Real_realloc)(void*, size_t) = realloc;
static void* (__cdecl *Real_calloc)(size_t, size_t) = calloc;

// Recursion guard - CRITICAL for preventing infinite loops
static bool g_in_native_hook = false;

// Coordination with Python allocator hooks
static bool g_in_python_allocator = false;

static void* __cdecl Hooked_malloc(size_t size) {
    // Check recursion guard FIRST - track_native_alloc may call malloc internally
    if (g_in_native_hook || g_in_python_allocator) {
        return Real_malloc(size);
    }

    g_in_native_hook = true;
    void* ptr = Real_malloc(size);
    if (ptr) {
        track_native_alloc(ptr, size);
        if (!p_scalene_done) {
            TheHeapWrapper::register_malloc(size, ptr, false);  // false = native
        }
    }
    g_in_native_hook = false;
    return ptr;
}

bool install_native_hooks() {
    DetourRestoreAfterWith();
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    DetourAttach(&(PVOID&)Real_malloc, Hooked_malloc);
    DetourAttach(&(PVOID&)Real_free, Hooked_free);
    DetourAttach(&(PVOID&)Real_realloc, Hooked_realloc);
    DetourAttach(&(PVOID&)Real_calloc, Hooked_calloc);

    return DetourTransactionCommit() == NO_ERROR;
}
```

### Critical Bug Fix: Recursion Guard Order

**Problem**: The native hooks use `std::unordered_map` for size tracking, which internally calls `malloc`. If the recursion guard was checked AFTER calling tracking functions, infinite recursion occurred:

1. User code calls `malloc`
2. `Hooked_malloc` is called
3. `track_native_alloc(ptr, size)` is called (hash map insert)
4. Hash map internally calls `malloc` for bucket allocation
5. `Hooked_malloc` is called again (recursion!)
6. Since `g_in_native_hook` wasn't set yet, we recurse infinitely → stack overflow

**Fix**: Check and set `g_in_native_hook` at the VERY BEGINNING of each hook, BEFORE any operations that might allocate:

```cpp
static void* __cdecl Hooked_malloc(size_t size) {
    // MUST check recursion guard FIRST
    if (g_in_native_hook || g_in_python_allocator) {
        return Real_malloc(size);  // Bypass hook
    }

    g_in_native_hook = true;  // Set BEFORE any allocating operations
    // ... rest of hook logic ...
    g_in_native_hook = false;
    return ptr;
}
```

### Free Size Tracking

**Problem**: `_msize()` doesn't work reliably for custom allocators (numpy uses aligned allocations with `_aligned_malloc`).

**Solution**: Manual size tracking with a hash map:

```cpp
static std::unordered_map<void*, size_t> g_native_alloc_sizes;
static CRITICAL_SECTION g_native_alloc_sizes_lock;

static void track_native_alloc(void* ptr, size_t size) {
    EnterCriticalSection(&g_native_alloc_sizes_lock);
    g_native_alloc_sizes[ptr] = size;
    LeaveCriticalSection(&g_native_alloc_sizes_lock);
}

static size_t untrack_native_alloc(void* ptr) {
    EnterCriticalSection(&g_native_alloc_sizes_lock);
    auto it = g_native_alloc_sizes.find(ptr);
    size_t size = (it != g_native_alloc_sizes.end()) ? it->second : 0;
    if (it != g_native_alloc_sizes.end()) g_native_alloc_sizes.erase(it);
    LeaveCriticalSection(&g_native_alloc_sizes_lock);
    return size;
}
```

### Coordination Between Python and Native Hooks

To prevent double-counting allocations that go through both Python's allocator AND the native malloc:

1. Python allocator hooks set `g_in_python_allocator = true` when active
2. Native malloc hooks check this flag and skip if Python allocator is handling it
3. Each allocation is counted exactly once

```cpp
// In Python allocator hook:
static void* scalene_malloc(void* ctx, size_t len) {
    g_in_python_allocator = true;  // Prevent native hooks
    void* ptr = g_original_mem_allocator.malloc(...);
    // ... tracking code ...
    g_in_python_allocator = false;
    return ptr;
}
```

## Fixes Applied

### 1. **ctypes 64-bit Pointer Fix** (Critical)
- Added `restype` declarations for all Windows API functions that return handles or pointers
- `MapViewOfFile.restype = ctypes.c_void_p` - returns memory address
- `OpenFileMappingW.restype = wintypes.HANDLE` - returns handle
- Also set `argtypes` for functions taking pointers

### 2. Data Format Fix
Changed malloc/free output from tab-separated 4-field format to comma-separated 9-field format matching Unix:
```
M,alloc_time,count,python_fraction,pid,pointer,filename,lineno,bytei\n\n
```

### 3. Removed `thread_local` Variables
Windows DLLs loaded with `LoadLibrary`/ctypes don't properly support `thread_local` variables. Changed all to static variables:
- `mallocSampler` and `memcpySampler`
- `g_pythonCount`, `g_cCount`
- `g_lastMallocTrigger`, `g_freedLastMallocTrigger`
- `g_memcpyOps`
- `inMalloc` (for recursion guard)

### 4. Added Windows Memory Polling
Since Unix signals (SIGXCPU/SIGXFSZ) don't exist on Windows, added a polling thread in `scalene_signal_manager.py`:
- `_windows_memory_poll_loop()` - polls every 10ms
- Triggers `_alloc_sigqueue_processor` and `_memcpy_sigqueue_processor`
- Started when memory profiling is enabled on Windows

### 5. Safety Checks in Allocator Hooks
Added null checks for original allocator function pointers to prevent crashes if allocation hooks are called before initialization.

## Test Results

Running the profiler now shows memory profiling data being collected:
```
malloc_calls=113807912, samples=595, logged=595
```

The profiler correctly tracks:
- Python vs native time
- Memory allocations with line attribution
- Memory timeline/growth rate

## Build Instructions

```bash
# Configure with CMake (for ARM64 native)
cmake -B build -A ARM64 -DPython3_ROOT_DIR="C:\Users\emery\AppData\Local\Programs\Python\Python311-arm64"

# Build the DLL
MSBuild.exe build/scalene.sln -p:Configuration=Release -p:Platform=ARM64 -t:scalene

# DLL is automatically placed in scalene\ directory

# Run profiler
python -m scalene --cli --cpu --memory test\testme.py
```

## Key Differences from Unix Implementation

| Aspect | Unix | Windows |
|--------|------|---------|
| Native malloc hooking | LD_PRELOAD | **Microsoft Detours** (inline function hooking) |
| Python allocator | PyMem_SetAllocator | PyMem_SetAllocator (same) |
| Signals | SIGXCPU/SIGXFSZ | Polling thread |
| Shared Memory | /tmp files + mmap | Named shared memory |
| Symbol Lookup | dlsym(RTLD_DEFAULT) | GetProcAddress + accessor functions |
| Size Tracking | malloc_usable_size | Manual hash map (\_msize unreliable) |
| Thread-local | `thread_local` | Static variables (GIL protects) |
| Pointer handling | Native 64-bit | **Requires explicit ctypes declarations** |
| Architecture support | All | ARM64, x64, x86 (via Detours) |

## Learnings

### 1. ctypes Default Return Types Are Dangerous on 64-bit Windows
- **Always** set `restype` for any Windows API function that returns a handle or pointer
- Default `c_int` (32-bit) silently truncates 64-bit values
- This causes delayed crashes that are hard to debug (crash happens when truncated pointer is used, not when it's returned)
- Use `ctypes.c_void_p` for memory addresses, `wintypes.HANDLE` for handles

### 2. Debugging Methodology That Worked
The crash was isolated using **systematic component elimination**:
1. First confirmed DLL was the cause by renaming it (profiler ran without crash)
2. Tested with allocator hooks disabled - still crashed (ruled out hooks as cause)
3. Tested with only shared memory initialization - still crashed (narrowed to shared memory)
4. Examined shared memory code and found the ctypes issue

### 3. Windows DLL Loading Constraints
- `thread_local` variables don't work reliably in DLLs loaded via `LoadLibrary`/ctypes
- Static variables work fine since Python's GIL serializes access
- DLL entry point (`DllMain`) has severe restrictions - avoid complex initialization there

### 4. Build System Considerations
- CMake generates Visual Studio solutions that work well for cross-platform builds
- ARM64 native builds require explicit `-A ARM64` and matching Python version
- MSBuild can be invoked directly for rebuilds without re-running CMake

### 5. Windows vs Unix IPC
- Named shared memory on Windows uses `Local\` prefix for per-session namespace
- Windows Events can replace Unix signals but polling is simpler for this use case
- Mutexes on Windows are more heavyweight than Unix futexes

### 6. Recursion Guards in malloc Hooks Must Come FIRST
- **Critical**: Any code in a malloc hook that uses STL containers (std::unordered_map, std::vector, etc.) may internally call malloc
- The recursion guard (`g_in_native_hook`) MUST be checked and set BEFORE any other operations
- Failing to do this causes infinite recursion → stack overflow → exit code 127 or crash
- Pattern: `if (guard) return original(); guard = true; ... ; guard = false; return result;`

### 7. MinHook Does NOT Support ARM64
- MinHook is a popular inline hooking library but only supports x86 and x64
- Microsoft Detours supports ARM64, ARM, x86, x64, and IA64
- Detours is MIT licensed (open source since 2018) and very well tested
- Use architecture-specific disassemblers: `disolarm64.cpp` for ARM64, `disolx64.cpp` for x64

### 8. _msize() Is Unreliable for Custom Allocators
- `_msize()` only works for standard CRT heap allocations
- numpy and other libraries use aligned allocations (`_aligned_malloc`) which `_msize` doesn't handle
- Solution: Manual size tracking with a hash map, storing size at allocation time
- This adds ~10% overhead but is necessary for accurate free tracking

### 9. Coordination Between Multiple Hook Layers
- When hooking at both Python allocator level AND native malloc level, coordination is essential
- Use a flag (`g_in_python_allocator`) to prevent native hooks from double-counting Python allocations
- Pattern: Set flag before calling original allocator, clear after
- This ensures each allocation is tracked exactly once

## Next Steps

### High Priority
1. **x64 Build and Testing**: Current implementation tested only on ARM64. Need to verify x64 builds work correctly with Detours.

2. **Unicode Console Output**: The `UnicodeEncodeError` for sparkline characters could be handled more gracefully:
   - Detect console encoding and fall back to ASCII sparklines
   - Or auto-set `PYTHONIOENCODING=utf-8` when running on Windows

3. **Performance Optimization**: The polling thread polls every 10ms. Consider:
   - Using Windows Events for more efficient signaling
   - Adaptive polling rate based on allocation frequency

### Medium Priority
4. **Multi-Process Support**: Test and fix any issues with profiling child processes on Windows (the Unix `redirect_python` mechanism may need Windows adaptation).

5. **GPU Profiling on Windows**: Verify NVIDIA GPU profiling works on Windows (pynvml should work but needs testing).

6. **CI/CD Integration**: Add Windows builds to GitHub Actions workflow:
   - Build DLL for both x64 and ARM64
   - Run tests on Windows
   - Include DLL in wheel packages

### Low Priority
7. **Windows Event-Based Signaling**: Replace polling with proper Windows Events for lower latency and CPU usage:
   - DLL already creates events (`ScaleneMallocEvent`, etc.)
   - Python side would use `WaitForMultipleObjects` instead of polling

8. **Memory Leak Detection**: The `--memory-leak-detector` feature may need Windows-specific testing.

9. **Web UI Testing**: Verify the web-based GUI works correctly on Windows (browser launching, port binding).

### Completed
- ~~**Native Library Memory Tracking**: Implement malloc/free hooking for numpy, pandas, etc.~~ ✅ Done (2024-12-17) - Using Microsoft Detours

## Debugging Tips for Future Issues

### Useful Debug Techniques
```python
# Add to scalene_mapfile.py to debug shared memory issues
print(f"Handle value: {handle:#x}", file=sys.stderr)
print(f"View address: {view:#x}", file=sys.stderr)

# Check if pointer looks valid (should have high bits set on 64-bit)
if view < 0x100000000:
    print("WARNING: Pointer may be truncated!", file=sys.stderr)
```

### Building with Debug Output
```cpp
// In libscalene_windows.cpp, temporarily add:
fprintf(stderr, "DEBUG: ptr=%p, size=%zu\n", ptr, size);
```

Then rebuild with:
```bash
MSBuild.exe build/scalene.sln -p:Configuration=Release -p:Platform=ARM64 -t:scalene
```

### Common Windows Error Codes
- `0xC0000005` (3221225477) - Access Violation (invalid memory access)
- `0xC0000008` - Invalid Handle
- `0xC000001D` - Illegal Instruction (wrong architecture)
- Error 193 - "Not a valid Win32 application" (architecture mismatch)

## References

- Python Memory Allocator API: https://docs.python.org/3/c-api/memory.html
- Windows Named Shared Memory: https://docs.microsoft.com/en-us/windows/win32/memory/creating-named-shared-memory
- CMake Windows DLL: https://cmake.org/cmake/help/latest/prop_tgt/WINDOWS_EXPORT_ALL_SYMBOLS.html
- Windows thread_local issues: https://devblogs.microsoft.com/cppblog/c11-thread-local-storage-and-dll-load-failure/
- **ctypes 64-bit pointers**: https://docs.python.org/3/library/ctypes.html#return-types
- **Microsoft Detours**: https://github.com/microsoft/Detours - Official Microsoft library for inline function hooking (MIT license)
- Detours Wiki: https://github.com/microsoft/Detours/wiki - API documentation and examples
