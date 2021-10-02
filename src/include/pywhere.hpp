#ifndef __PYWHERE_H
#define __PYWHERE_H

#include <string>

/**
 * Examines the current Python stack frame and let us know where in the code we are.
 */
extern "C" int whereInPython(std::string& filename, int& lineno, int& bytei);


/**
 * Pointer to "whereInPython" for efficient linkage between pywhere and libscalene.
 */
extern "C" _Atomic(decltype(whereInPython)*) p_whereInPython;

#endif
