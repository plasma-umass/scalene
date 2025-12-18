cmake_minimum_required(VERSION 3.15)
project(scalene VERSION 1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# FetchContent for downloading dependencies
include(FetchContent)

# Find Python
find_package(Python3 REQUIRED COMPONENTS Development)

# Detect architecture
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|ARM64|arm64")
    set(SCALENE_ARCH "ARM64")
    message(STATUS "Building for ARM64 architecture")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "AMD64|x86_64")
    set(SCALENE_ARCH "X64")
    message(STATUS "Building for x86-64 architecture")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "i[3-6]86|x86")
    set(SCALENE_ARCH "X86")
    message(STATUS "Building for x86 architecture")
else()
    message(WARNING "Unknown architecture: ${CMAKE_SYSTEM_PROCESSOR}")
    set(SCALENE_ARCH "UNKNOWN")
endif()

# Common include directories
set(SCALENE_INCLUDES
    ${CMAKE_SOURCE_DIR}/src
    ${CMAKE_SOURCE_DIR}/src/include
    ${CMAKE_SOURCE_DIR}/vendor/Heap-Layers
    ${CMAKE_SOURCE_DIR}/vendor/Heap-Layers/heaps
    ${CMAKE_SOURCE_DIR}/vendor/Heap-Layers/heaps/threads
    ${CMAKE_SOURCE_DIR}/vendor/Heap-Layers/heaps/utility
    ${CMAKE_SOURCE_DIR}/vendor/Heap-Layers/wrappers
    ${CMAKE_SOURCE_DIR}/vendor/Heap-Layers/utility
    ${CMAKE_SOURCE_DIR}/vendor/printf
    ${Python3_INCLUDE_DIRS}
)

# Platform-specific configuration
if(WIN32)
    # Windows build
    message(STATUS "Configuring Windows build")

    # Download Microsoft Detours for native malloc/free hooking
    FetchContent_Declare(
        detours
        GIT_REPOSITORY https://github.com/microsoft/Detours.git
        GIT_TAG        main
        GIT_SHALLOW    TRUE
    )
    FetchContent_MakeAvailable(detours)

    # Microsoft Detours sources
    set(DETOURS_SOURCES
        ${detours_SOURCE_DIR}/src/detours.cpp
        ${detours_SOURCE_DIR}/src/modules.cpp
        ${detours_SOURCE_DIR}/src/disasm.cpp
        ${detours_SOURCE_DIR}/src/image.cpp
        ${detours_SOURCE_DIR}/src/creatwth.cpp
    )

    # Add architecture-specific disassembler
    if(SCALENE_ARCH STREQUAL "ARM64")
        list(APPEND DETOURS_SOURCES ${detours_SOURCE_DIR}/src/disolarm64.cpp)
        message(STATUS "Using ARM64 Detours disassembler")
    elseif(SCALENE_ARCH STREQUAL "X64")
        list(APPEND DETOURS_SOURCES ${detours_SOURCE_DIR}/src/disolx64.cpp)
        message(STATUS "Using x64 Detours disassembler")
    elseif(SCALENE_ARCH STREQUAL "X86")
        list(APPEND DETOURS_SOURCES ${detours_SOURCE_DIR}/src/disolx86.cpp)
        message(STATUS "Using x86 Detours disassembler")
    endif()

    add_library(scalene SHARED
        src/source/libscalene_windows.cpp
        vendor/printf/printf.cpp
        ${DETOURS_SOURCES}
    )

    target_include_directories(scalene PRIVATE
        ${SCALENE_INCLUDES}
        ${detours_SOURCE_DIR}/src
    )

    target_compile_definitions(scalene PRIVATE
        WIN32_LEAN_AND_MEAN
        _REENTRANT=1
        NDEBUG
        HL_USE_XXREALLOC=1
        SCALENE_LIBSCALENE_BUILD=1
        _CRT_SECURE_NO_WARNINGS=1
    )

    target_compile_options(scalene PRIVATE
        /W3
        /O2
        /EHsc
    )

    target_link_libraries(scalene PRIVATE
        kernel32
        user32
        psapi
        ${Python3_LIBRARIES}
    )

    # Output to scalene directory (without Release/Debug subdirectory)
    set_target_properties(scalene PROPERTIES
        OUTPUT_NAME "libscalene"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/scalene"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/scalene"
        # Prevent MSBuild from adding configuration subdirectories
        LIBRARY_OUTPUT_DIRECTORY_DEBUG "${CMAKE_SOURCE_DIR}/scalene"
        LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/scalene"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_SOURCE_DIR}/scalene"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/scalene"
    )

elseif(APPLE)
    # macOS build
    message(STATUS "Configuring macOS build")

    add_library(scalene SHARED
        src/source/libscalene.cpp
        vendor/Heap-Layers/wrappers/macwrapper.cpp
        vendor/printf/printf.cpp
    )

    target_include_directories(scalene PRIVATE ${SCALENE_INCLUDES})

    target_compile_definitions(scalene PRIVATE
        _REENTRANT=1
        NDEBUG
        HL_USE_XXREALLOC=1
    )

    target_compile_options(scalene PRIVATE
        -Wall
        -O3
        -fno-builtin-malloc
        -fvisibility=hidden
        -flto
        -ftls-model=initial-exec
        -ftemplate-depth=1024
    )

    # Universal binary support (x86_64 and arm64)
    if(CMAKE_OSX_ARCHITECTURES)
        # Use specified architectures
    else()
        # Default to native architecture
        set(CMAKE_OSX_ARCHITECTURES "${CMAKE_SYSTEM_PROCESSOR}")
    endif()

    target_link_libraries(scalene PRIVATE
        dl
        pthread
    )

    set_target_properties(scalene PROPERTIES
        OUTPUT_NAME "scalene"
        PREFIX "lib"
        SUFFIX ".dylib"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/scalene"
    )

else()
    # Linux build
    message(STATUS "Configuring Linux build")

    add_library(scalene SHARED
        src/source/libscalene.cpp
        vendor/Heap-Layers/wrappers/gnuwrapper.cpp
        vendor/printf/printf.cpp
    )

    target_include_directories(scalene PRIVATE
        ${SCALENE_INCLUDES}
        /usr/include/nptl
    )

    target_compile_definitions(scalene PRIVATE
        _REENTRANT=1
        NDEBUG
        HL_USE_XXREALLOC=1
    )

    target_compile_options(scalene PRIVATE
        -Wall
        -O3
        -pipe
        -fno-builtin-malloc
        -fvisibility=hidden
        -fPIC
        -Bsymbolic
    )

    target_link_libraries(scalene PRIVATE
        dl
        pthread
    )

    set_target_properties(scalene PROPERTIES
        OUTPUT_NAME "scalene"
        PREFIX "lib"
        SUFFIX ".so"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/scalene"
    )
endif()

# Installation
install(TARGETS scalene
    LIBRARY DESTINATION scalene
    RUNTIME DESTINATION scalene
)

# Custom target for vendored dependencies
add_custom_target(vendor-deps
    COMMAND ${CMAKE_COMMAND} -E echo "Checking vendor dependencies..."
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)

# Ensure vendor dependencies exist
if(NOT EXISTS "${CMAKE_SOURCE_DIR}/vendor/Heap-Layers/heaplayers.h")
    message(WARNING "Heap-Layers not found. Run 'make vendor-deps' or clone manually.")
endif()

if(NOT EXISTS "${CMAKE_SOURCE_DIR}/vendor/printf/printf.cpp")
    message(WARNING "printf not found. Run 'make vendor-deps' or clone manually.")
endif()
