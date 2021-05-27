LIBNAME = scalene
PYTHON = python3
PYTHON_SOURCES = scalene/[a-z]*.py
C_SOURCES = src/source/libscalene.cpp src/source/get_line_atomic.cpp src/include/*.h*

CXXFLAGS = /Ox /DNDEBUG /std:c++14 /Zi
CXX = cl

MAIN_INCLUDES  = -Isrc -Isrc/include
INCLUDES = $(MAIN_INCLUDES) -Ivendor/Heap-Layers -Ivendor/Heap-Layers/wrappers -Ivendor/Heap-Layers/utility -Ivendor/printf

LIBFILE = lib$(LIBNAME).dll
WRAPPER = vendor/Heap-Layers/wrappers/gnuwrapper.cpp

SRC = src/source/lib$(LIBNAME).cpp $(WRAPPER) vendor/printf/printf.cpp

all: vendor/Heap-Layers $(SRC) $(OTHER_DEPS)

#	del /F /Q $(LIBFILE) scalene\$(LIBFILE)
#	$(CXX) $(CXXFLAGS) $(INCLUDES) $(SRC) /o $(LIBFILE)
#	cp $(LIBFILE) scalene

$(WRAPPER) : vendor/Heap-Layers

vendor/Heap-Layers:
	git clone https://github.com/emeryberger/Heap-Layers -o vendor/Heap-Layers

vendor/Hoard:
	git clone https://github.com/emeryberger/Hoard -o vendor/Hoard
	cd vendor/Hoard/src && mklink ../../Heap-Layers Heap-Layers

vendor/printf/printf.cpp:
	git clone https://github.com/mpaland/printf -o vendor/printf
	cd vendor/printf && mklink printf.cpp printf.c

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
