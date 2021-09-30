#ifndef __PYWHERE_H
#define __PYWHERE_H

#include <string>

extern "C" int whereInPython(std::string& filename, int& lineno, int& bytei);

#endif
