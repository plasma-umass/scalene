CPPFLAGS = -std=c++17 -g -O3 -flto -DNDEBUG -fno-builtin-malloc -fvisibility=hidden
CXX = clang++

INCLUDES = -I. -I./include -IHeap-Layers -IHeap-Layers/wrappers -IHeap-Layers/utility

MACOS_SRC = lib$(LIBNAME).cpp Heap-Layers/wrappers/macwrapper.cpp
MACOS_COMPILE = $(CXX) -ftls-model=initial-exec -ftemplate-depth=1024 -arch x86_64 -pipe $(CPPFLAGS) $(INCLUDES) -D_REENTRANT=1 -compatibility_version 1 -current_version 1 -D'CUSTOM_PREFIX(x)=xx\#\#x' $(MACOS_SRC) -dynamiclib -install_name $(DESTDIR)$(PREFIX)/lib$(LIBNAME).dylib -o lib$(LIBNAME).dylib -ldl -lpthread 

LINUX_SRC = lib$(LIBNAME).cpp Heap-Layers/wrappers/gnuwrapper.cpp
LINUX_COMPILE = $(CXX) $(CPPFLAGS) -D'CUSTOM_PREFIX(x)=xx\#\#x' -I/usr/include/nptl -fno-builtin-malloc -pipe -fPIC $(INCLUDES) -D_REENTRANT=1 -shared $(LINUX_SRC) -Bsymbolic -o lib$(LIBNAME).so -ldl -lpthread

UNAME_S := $(shell uname -s)
UNAME_P := $(shell uname -p)

ifeq ($(UNAME_S),Darwin)
  all: Heap-Layers $(MACOS_SRC)
	$(MACOS_COMPILE)
endif

ifeq ($(UNAME_S),Linux)
  all: Heap-Layers $(LINUX_SRC)
	$(LINUX_COMPILE)
endif

Heap-Layers:
	git clone https://github.com/emeryberger/Heap-Layers
