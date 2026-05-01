#ifndef __PYWHERE_H
#define __PYWHERE_H

#include <atomic>
#include <stddef.h>
#include <string>

// On Windows, we need dllexport/dllimport for cross-DLL symbol visibility
#if defined(_WIN32)
  #if defined(SCALENE_LIBSCALENE_BUILD)
    #define SCALENE_PYWHERE_API __declspec(dllexport)
  #else
    #define SCALENE_PYWHERE_API __declspec(dllimport)
  #endif
#else
  #define SCALENE_PYWHERE_API
#endif

/**
 * Examines the current Python stack frame and let us know where in the code we
 * are.
 */
extern "C" int whereInPython(std::string& filename, int& lineno, int& bytei);

/**
 * Like whereInPython, but also writes every traced frame (leaf-first) into
 * a caller-supplied character buffer as "|filename;lineno" records
 * concatenated together, producing for example "|foo.py;42|bar.py;7".
 *
 * The buffer form is chosen deliberately so the sampler does not have to
 * allocate (no std::vector, no std::string churn) while it is itself trying
 * to record a malloc sample — allocating inside the sampler would either
 * recurse through the profiler or leave observable artifacts in the output.
 *
 * If ``stack_buf`` is nullptr or ``stack_buf_size`` is 0, no stack is
 * recorded (equivalent to whereInPython). When the buffer is full the
 * remaining frames are silently dropped; the frames that made it in are
 * still valid. The caller must NUL-terminate the buffer before use.
 * ``stack_bytes_written`` is set to the number of bytes written (excluding
 * the NUL terminator the caller should add).
 */
extern "C" int whereInPythonWithStack(std::string& filename, int& lineno,
                                      int& bytei, char* stack_buf,
                                      size_t stack_buf_size,
                                      size_t* stack_bytes_written);

/**
 * Pointer to "whereInPythonWithStack" for efficient linkage between pywhere
 * and libscalene — same rationale as p_whereInPython.
 */
#if defined(_WIN32)
SCALENE_PYWHERE_API extern std::atomic<decltype(whereInPythonWithStack)*>
    p_whereInPythonWithStack;
#else
extern "C" SCALENE_PYWHERE_API
    std::atomic<decltype(whereInPythonWithStack)*> p_whereInPythonWithStack;
#endif

/**
 * Pointer to "whereInPython" for efficient linkage between pywhere and
 * libscalene.
 *
 * Note: extern "C" with std::atomic is technically invalid C linkage, but
 * it works for symbol export purposes. On Windows, we use accessor functions
 * (get_p_whereInPython, get_p_scalene_done) to find these via GetProcAddress.
 */
#if defined(_WIN32)
// On Windows, these are defined in libscalene_windows.cpp without extern "C"
// pywhere.cpp uses accessor functions to get pointers to them
SCALENE_PYWHERE_API extern std::atomic<decltype(whereInPython)*> p_whereInPython;
SCALENE_PYWHERE_API extern std::atomic<bool> p_scalene_done;
#else
extern "C" SCALENE_PYWHERE_API std::atomic<decltype(whereInPython)*> p_whereInPython;
extern "C" SCALENE_PYWHERE_API std::atomic<bool> p_scalene_done;
#endif

/**
 * Returns whether the Python interpreter was detected.
 * It's possible (and in fact happens for any fork/exec from within Python,
 * given the preload environment variables) for libscalene to be preloaded onto
 * a different executable.
 */
inline bool pythonDetected() { return p_whereInPython != nullptr; }
#endif
