LIBNAME = scalene
PYTHON = python3
PYTHON_SOURCES = scalene/[a-z]*.py
C_SOURCES = src/source/libscalene.cpp src/source/get_line_atomic.cpp src/include/*.h*

.PHONY: black clang-format format upload

# CXXFLAGS = -std=c++14 -g -O0
CXXFLAGS = -std=c++14 -g -O3 -DNDEBUG -D_REENTRANT=1 -D'CUSTOM_PREFIX(x)=xx\#\#x' -pipe -fno-builtin-malloc -fvisibility=hidden
CXX = clang++

INCLUDES  = -Isrc -Isrc/include
INCLUDES := $(INCLUDES) -Ivendor/Heap-Layers -Ivendor/Heap-Layers/wrappers -Ivendor/Heap-Layers/utility
INCLUDES := $(INCLUDES) -Ivendor/printf

ifeq ($(shell uname -s),Darwin)
  LIBFILE := lib$(LIBNAME).dylib
  WRAPPER := vendor/Heap-Layers/wrappers/macwrapper.cpp
	ifneq (,$(filter $(shell uname -s),arm arm64))
    ARMFLAG = -arch arm64 
  endif
  CXXFLAGS := $(CXXFLAGS) -flto -ftls-model=initial-exec -ftemplate-depth=1024 -arch x86_64 $(ARMFLAG) -compatibility_version 1 -current_version 1 -dynamiclib

  INCLUDES := $(INCLUDES) -Ivendor/Hoard/src/include/hoard -Ivendor/Hoard/src/include/util -Ivendor/Hoard/src/include/superblocks
  OTHER_DEPS := vendor/Hoard

else # non-Darwin
  LIBFILE := lib$(LIBNAME).so
  WRAPPER := vendor/Heap-Layers/wrappers/gnuwrapper.cpp
  INCLUDES := $(INCLUDES) -I/usr/include/nptl 
  CXXFLAGS := $(CXXFLAGS) -fPIC -shared -Bsymbolic

endif

SRC := src/source/lib$(LIBNAME).cpp $(WRAPPER) vendor/printf/printf.cpp

all: vendor/Heap-Layers $(SRC) $(OTHER_DEPS)
	rm -f $(LIBFILE) scalene/$(LIBFILE)
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(SRC) -o $(LIBFILE) -ldl -lpthread
	cp $(LIBFILE) scalene

$(WRAPPER) : vendor/Heap-Layers

vendor/Heap-Layers:
	mkdir -p vendor && cd vendor && git clone https://github.com/emeryberger/Heap-Layers

vendor/Hoard:
	mkdir -p vendor && cd vendor && git clone https://github.com/emeryberger/Hoard
	cd vendor/Hoard/src && ln -s ../../Heap-Layers  # avoid inconsistencies by using same package

vendor/printf/printf.cpp:
	mkdir -p vendor && cd vendor && git clone https://github.com/mpaland/printf
	cd vendor/printf && ln -s printf.c printf.cpp

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
