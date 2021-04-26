LIBNAME = scalene
PYTHON = python3
PYTHON_SOURCES = scalene/[a-z]*.py
C_SOURCES = src/source/libscalene.cpp src/source/get_line_atomic.cpp src/include/*.h*

.PHONY: black clang-format format upload

SRC = vendor/printf/printf.c
INCLUDES = -Isrc/include -Ivendor/printf
OTHER_DEPS = vendor/printf

include heaplayers-make.mk

vendor/printf/printf.c: vendor/printf

vendor/printf:
	mkdir -p vendor && cd vendor && git clone https://github.com/mpaland/printf

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
