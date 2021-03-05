# CPPFLAGS = -std=c++14 -g -O0
CPPFLAGS = -std=c++17 -g -O3 -DNDEBUG -fno-builtin-malloc -fvisibility=hidden
CXX = clang++

INCLUDES = -I. -I./include -IHeap-Layers -IHeap-Layers/wrappers -IHeap-Layers/utility

MACOS_SRC = lib$(LIBNAME).cpp Heap-Layers/wrappers/macwrapper.cpp
MACOS_COMPILE = $(CXX) -flto -ftls-model=initial-exec -ftemplate-depth=1024 -arch x86_64 -arch arm64 -pipe $(CPPFLAGS) $(INCLUDES) -D_REENTRANT=1 -compatibility_version 1 -current_version 1 -D'CUSTOM_PREFIX(x)=xx\#\#x' $(MACOS_SRC) -dynamiclib -install_name $(DESTDIR)$(PREFIX)/lib$(LIBNAME).dylib -o lib$(LIBNAME).dylib -ldl -lpthread 

LINUX_SRC = lib$(LIBNAME).cpp Heap-Layers/wrappers/gnuwrapper.cpp
LINUX_COMPILE = $(CXX) $(CPPFLAGS) -D'CUSTOM_PREFIX(x)=xx\#\#x' -I/usr/include/nptl -pipe -fPIC $(INCLUDES) -D_REENTRANT=1 -shared $(LINUX_SRC) -Bsymbolic -o lib$(LIBNAME).so -ldl -lpthread

UNAME_S := $(shell uname -s)
UNAME_P := $(shell uname -p)

ifeq ($(UNAME_S),Darwin)
  all: Heap-Layers $(MACOS_SRC)
	rm -f lib$(LIBNAME).dylib scalene/lib$(LIBNAME).dylib
	$(MACOS_COMPILE)
	cp lib$(LIBNAME).dylib scalene
endif

ifeq ($(UNAME_S),Linux)
  all: Heap-Layers $(LINUX_SRC)
	$(LINUX_COMPILE)
	cp lib$(LIBNAME).so scalene
endif

Heap-Layers:
	git clone https://github.com/emeryberger/Heap-Layers
