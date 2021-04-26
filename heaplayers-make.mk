# CPPFLAGS = -std=c++14 -g -O0
CPPFLAGS = -std=c++14 -g -O3 -DNDEBUG -fno-builtin-malloc -fvisibility=hidden
CXX = clang++

UNAME_S := $(shell uname -s)
UNAME_P := $(shell uname -p)
ifeq ($(UNAME_S),Darwin)
	ifeq ($(UNAME_P),arm)
		ARMFLAG = -arch arm64 
	endif
	ifeq ($(UNAME_P),arm64)
		ARMFLAG = -arch arm64 
	endif
endif
INCLUDES := $(INCLUDES) -Isrc -Isrc/include -Ivendor/Heap-Layers -Ivendor/Heap-Layers/wrappers -Ivendor/Heap-Layers/utility -Ivendor/printf

MACOS_SRC := $(SRC) src/source/lib$(LIBNAME).cpp vendor/Heap-Layers/wrappers/macwrapper.cpp
MACOS_COMPILE = $(CXX) -flto -ftls-model=initial-exec -ftemplate-depth=1024 -arch x86_64 $(ARMFLAG) -pipe $(CPPFLAGS) $(INCLUDES) -D_REENTRANT=1 -compatibility_version 1 -current_version 1 -D'CUSTOM_PREFIX(x)=xx\#\#x' $(MACOS_SRC) -dynamiclib -install_name $(DESTDIR)$(PREFIX)/lib$(LIBNAME).dylib -o lib$(LIBNAME).dylib -ldl -lpthread 

LINUX_SRC := $(SRC) src/source/lib$(LIBNAME).cpp vendor/Heap-Layers/wrappers/gnuwrapper.cpp
LINUX_COMPILE = $(CXX) $(CPPFLAGS) -D'CUSTOM_PREFIX(x)=xx\#\#x' -I/usr/include/nptl -pipe -fPIC $(INCLUDES) -D_REENTRANT=1 -shared $(LINUX_SRC) -Bsymbolic -o lib$(LIBNAME).so -ldl -lpthread


ifeq ($(UNAME_S),Darwin)
  all: vendor/Heap-Layers $(MACOS_SRC) $(OTHER_DEPS)
	rm -f lib$(LIBNAME).dylib scalene/lib$(LIBNAME).dylib
	$(MACOS_COMPILE)
	cp lib$(LIBNAME).dylib scalene
endif

ifeq ($(UNAME_S),Linux)
  all: vendor/Heap-Layers $(LINUX_SRC) $(OTHER_DEPS)
	$(LINUX_COMPILE)
	cp lib$(LIBNAME).so scalene
endif

vendor/Heap-Layers:
	mkdir -p vendor && cd vendor && git clone https://github.com/emeryberger/Heap-Layers
