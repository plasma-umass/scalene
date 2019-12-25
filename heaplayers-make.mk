CPPFLAGS = -std=c++14 -g -DNDEBUG -O3 -ffast-math -fno-builtin-malloc # -Wall -Wextra -Wshadow -Wconversion -Wuninitialized
CXX = clang++

INCLUDES = -I. -IHeap-Layers -IHeap-Layers/utility
MACOS_SRC = lib$(LIBNAME).cpp Heap-Layers/wrappers/macwrapper.cpp
MACOS_COMPILE = $(CXX) -ftemplate-depth=1024 -arch x86_64 -pipe -g $(CPPFLAGS) $(INCLUDES) -D_REENTRANT=1 -compatibility_version 1 -current_version 1 -D'CUSTOM_PREFIX(x)=xx\#\#x' $(MACOS_SRC) -dynamiclib -install_name $(DESTDIR)$(PREFIX)/lib$(LIBNAME).dylib -o lib$(LIBNAME).dylib -ldl -lpthread 

UNAME_S := $(shell uname -s)
UNAME_P := $(shell uname -p)

ifeq ($(UNAME_S),Darwin)
  all:
	$(MACOS_COMPILE)
endif

Heap-Layers:
	git clone https://github.com/emeryberger/Heap-Layers
