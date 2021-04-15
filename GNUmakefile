LIBNAME = scalene
PYTHON = python3
PYTHON_SOURCES = scalene/[a-z]*.py
C_SOURCES = libscalene.cpp get_line_atomic.cpp include/*.h*

.PHONY: black clang-format

SRC = printf/printf.c
INCLUDES = -Iprintf
OTHER_DEPS = printf

include heaplayers-make.mk

printf/printf.c: printf

printf:
	git clone https://github.com/mpaland/printf

mypy:
	-mypy $(PYTHON_SOURCES)

format: black clang-format

clang-format:
	-clang-format -i $(C_SOURCES) --style=google

black:
	-black -l 79 $(PYTHON_SOURCES)

upload: # to pypi
	-cp libscalene.so libscalene.dylib scalene/
	-rm -rf build dist *egg-info
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/*
