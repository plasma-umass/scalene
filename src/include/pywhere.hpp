#ifndef __PYWHERE_H
#define __PYWHERE_H

#include <atomic>
#include <string>

/**
 * Examines the current Python stack frame and let us know where in the code we
 * are.
 */
extern "C" int whereInPython(std::string& filename, int& lineno, int& bytei);

/**
 * Pointer to "whereInPython" for efficient linkage between pywhere and
 * libscalene.
 */
extern "C" std::atomic<decltype(whereInPython)*> p_whereInPython;

/**
 * Returns whether the Python interpreter was detected.
 * It's possible (and in fact happens for any fork/exec from within Python,
 * given the preload environment variables) for libscalene to be preloaded onto
 * a different executable.
 */
inline bool pythonDetected() { return p_whereInPython != nullptr; }
#endif
