LIBNAME = scalene
PYTHON = python3
PYTHON_SOURCES = scalene/[a-z]*.py
JS_SOURCES = scalene/scalene-gui/*.js
C_SOURCES = src/source/*.cpp src/include/*.h*

.PHONY: black clang-format prettier format upload vendor-deps

# CXXFLAGS = -std=c++14 -g -O0 # FIXME
CXXFLAGS = -std=c++14 -Wall -g -O3 -DNDEBUG -D_REENTRANT=1 -DHL_USE_XXREALLOC=1 -pipe -fno-builtin-malloc -fvisibility=hidden -Wno-unused-result
# CXX = g++

INCLUDES  = -Isrc -Isrc/include
INCLUDES := $(INCLUDES) -Ivendor/Heap-Layers -Ivendor/Heap-Layers/wrappers -Ivendor/Heap-Layers/utility
INCLUDES := $(INCLUDES) -Ivendor/printf
# python3-config may not be available in venv and such
INCLUDES := $(INCLUDES) -I$(shell python3 -c "import sysconfig; print(sysconfig.get_path('include'))")

ifeq ($(shell uname -s),Darwin)
  LIBFILE := lib$(LIBNAME).dylib
  WRAPPER := vendor/Heap-Layers/wrappers/macwrapper.cpp
  ifneq (,$(filter $(shell uname -p),arm arm64))  # this means "if arm or arm64"
    ARCH := -arch arm64 -arch arm64e 
  else
    ARCH := -arch x86_64
  endif
  CXXFLAGS := -std=c++14 -Wall -g -O3 -DNDEBUG -D_REENTRANT=1 -DHL_USE_XXREALLOC=1 -pipe -fno-builtin-malloc -fvisibility=hidden -flto -ftls-model=initial-exec -ftemplate-depth=1024 $(ARCH) -compatibility_version 1 -current_version 1 -dynamiclib
  SED_INPLACE = -i ''

else # non-Darwin
  LIBFILE := lib$(LIBNAME).so
  WRAPPER := vendor/Heap-Layers/wrappers/gnuwrapper.cpp
  INCLUDES := $(INCLUDES) -I/usr/include/nptl 
  CXXFLAGS := $(CXXFLAGS) -fPIC -shared -Bsymbolic
  RPATH_FLAGS :=
  SED_INPLACE = -i

endif

SRC := src/source/lib$(LIBNAME).cpp $(WRAPPER) vendor/printf/printf.cpp

OUTDIR=scalene

all: $(OUTDIR)/$(LIBFILE)

$(OUTDIR)/$(LIBFILE): vendor-deps $(SRC) $(C_SOURCES) GNUmakefile
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(SRC) -o $(OUTDIR)/$(LIBFILE) -ldl -lpthread

clean:
	rm -f $(OUTDIR)/$(LIBFILE) scalene/*.so scalene/*.dylib
	rm -rf $(OUTDIR)/$(LIBFILE).dSYM
	rm -rf scalene.egg-info
	rm -rf build dist *egg-info

$(WRAPPER) : vendor/Heap-Layers

vendor/Heap-Layers:
	mkdir -p vendor && cd vendor && git clone https://github.com/emeryberger/Heap-Layers

TMP := $(shell mktemp -d || echo /tmp)

vendor/printf/printf.cpp:
	mkdir -p vendor && cd vendor && git clone https://github.com/mpaland/printf
	cd vendor/printf && ln -s printf.c printf.cpp
	sed -e 's/^#define printf printf_/\/\/&/' vendor/printf/printf.h > $(TMP)/printf.h.$$ && mv $(TMP)/printf.h.$$ vendor/printf/printf.h
	sed -e 's/^#define vsnprintf vsnprintf_/\/\/&/' vendor/printf/printf.h > $(TMP)/printf.h.$$ && mv $(TMP)/printf.h.$$ vendor/printf/printf.h

# libunwind: only vendored/built on Linux. macOS uses system <unwind.h> (_Unwind_Backtrace).
LIBUNWIND_VERSION := 1.8.1
LIBUNWIND_DIR := vendor/libunwind
LIBUNWIND_LIB  := $(LIBUNWIND_DIR)/src/.libs/libunwind.a

ifeq ($(shell uname -s),Linux)
LIBUNWIND_TARGET := $(LIBUNWIND_LIB)
else
LIBUNWIND_TARGET :=
endif

$(LIBUNWIND_DIR)/configure:
	mkdir -p vendor
	cd vendor && curl -fsSL https://github.com/libunwind/libunwind/releases/download/v$(LIBUNWIND_VERSION)/libunwind-$(LIBUNWIND_VERSION).tar.gz | tar xz
	rm -rf $(LIBUNWIND_DIR)
	mv vendor/libunwind-$(LIBUNWIND_VERSION) $(LIBUNWIND_DIR)

$(LIBUNWIND_LIB): $(LIBUNWIND_DIR)/configure
	cd $(LIBUNWIND_DIR) && \
	  ./configure --enable-static --disable-shared --disable-tests \
	              --disable-documentation --disable-coredump \
	              --disable-ptrace --disable-setjmp \
	              --disable-minidebuginfo --disable-zlibdebuginfo \
	              CFLAGS="-fPIC -O2" && \
	  $(MAKE) -j

vendor-deps: vendor/Heap-Layers vendor/printf/printf.cpp $(LIBUNWIND_TARGET)

mypy:
	# Requires: pip install mypy types-PyYAML
	-mypy $(PYTHON_SOURCES)

format: black clang-format prettier

clang-format:
	-clang-format -i $(C_SOURCES) --style=google

black:
	-black -l 79 $(PYTHON_SOURCES)

prettier:
	-npx prettier -w $(JS_SOURCES)

bdist: vendor-deps
	$(PYTHON) -m build --wheel
ifeq ($(shell uname -s),Linux)
	auditwheel repair dist/*.whl
	rm -f dist/*.whl
	mv wheelhouse/*.whl dist/
endif

sdist: vendor-deps
	$(PYTHON) -m build --sdist

upload: sdist bdist # to pypi
	$(PYTHON) -m twine upload dist/*
