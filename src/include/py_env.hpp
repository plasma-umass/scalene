#ifndef __PYENV_H
#define __PYENV_H

#include <string>

extern "C" int getPythonInfo(std::string& filename, int& lineno, int& bytei);

#endif
