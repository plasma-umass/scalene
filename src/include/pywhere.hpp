#ifndef __PYWHERE_H
#define __PYWHERE_H

#include <atomic>
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
