#pragma once
#ifndef SAMPLEFILE_WIN_H
#define SAMPLEFILE_WIN_H

#if defined(_WIN32)

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <process.h>

// Use Windows _snprintf_s instead of printf library's snprintf_
// to avoid any potential issues during DLL init
#define snprintf_for_init(buf, size, fmt, ...) _snprintf_s(buf, size, _TRUNCATE, fmt, __VA_ARGS__)

// Windows-specific SampleFile implementation using named shared memory
// This replaces the POSIX mmap-based implementation for Windows

class SampleFile {
 public:
  static constexpr int MAX_BUFSIZE = 4096;

 private:
  static constexpr int LOCK_SIZE = 4096;
  static constexpr int MAX_FILE_SIZE = 4096 * 65536;

 public:
  SampleFile(const char *name_template, const char *lockname_template,
             const char *init_template) {
    int base_pid = _getpid();

    // Create unique names for shared memory objects
    // Use Windows _snprintf_s to avoid any malloc during init
    snprintf_for_init(_signalname, MAX_BUFSIZE - 1, name_template, base_pid);
    snprintf_for_init(_lockname, MAX_BUFSIZE - 1, lockname_template, base_pid);
    snprintf_for_init(_initname, MAX_BUFSIZE - 1, init_template, base_pid);

    // Convert forward slashes to backslashes and /tmp to Local\\
    // Windows named objects use different namespace
    convertToWindowsName(_signalname);
    convertToWindowsName(_lockname);
    convertToWindowsName(_initname);

    // Create file mapping for signal data
    _hMapFile = CreateFileMappingA(
        INVALID_HANDLE_VALUE,    // use paging file
        NULL,                    // default security
        PAGE_READWRITE,          // read/write access
        0,                       // max size high
        MAX_FILE_SIZE,           // max size low
        _signalname);            // name of mapping object

    if (_hMapFile == NULL) {
      fprintf(stderr, "Scalene: internal error creating file mapping = %lu (%s:%d)\n",
              GetLastError(), __FILE__, __LINE__);
      return;
    }

    _mmap = (char *)MapViewOfFile(
        _hMapFile,
        FILE_MAP_ALL_ACCESS,
        0, 0,
        MAX_FILE_SIZE);

    if (_mmap == NULL) {
      fprintf(stderr, "Scalene: internal error mapping view = %lu (%s:%d)\n",
              GetLastError(), __FILE__, __LINE__);
      CloseHandle(_hMapFile);
      _hMapFile = NULL;
      return;
    }

    // Create file mapping for lock/position data
    _hLockFile = CreateFileMappingA(
        INVALID_HANDLE_VALUE,
        NULL,
        PAGE_READWRITE,
        0,
        LOCK_SIZE,
        _lockname);

    if (_hLockFile == NULL) {
      fprintf(stderr, "Scalene: internal error creating lock mapping = %lu (%s:%d)\n",
              GetLastError(), __FILE__, __LINE__);
      UnmapViewOfFile(_mmap);
      CloseHandle(_hMapFile);
      _mmap = nullptr;
      _hMapFile = NULL;
      return;
    }

    _lastpos = (uint64_t *)MapViewOfFile(
        _hLockFile,
        FILE_MAP_ALL_ACCESS,
        0, 0,
        LOCK_SIZE);

    if (_lastpos == NULL) {
      fprintf(stderr, "Scalene: internal error mapping lock view = %lu (%s:%d)\n",
              GetLastError(), __FILE__, __LINE__);
      UnmapViewOfFile(_mmap);
      CloseHandle(_hMapFile);
      CloseHandle(_hLockFile);
      _mmap = nullptr;
      _hMapFile = NULL;
      _hLockFile = NULL;
      return;
    }

    // Create mutex for synchronization
    _hMutex = CreateMutexA(NULL, FALSE, _initname);
    if (_hMutex == NULL) {
      fprintf(stderr, "Scalene: internal error creating mutex = %lu (%s:%d)\n",
              GetLastError(), __FILE__, __LINE__);
    }

    // Initialize position if we're the first
    if (GetLastError() != ERROR_ALREADY_EXISTS) {
      *_lastpos = 0;
    }
  }

  ~SampleFile() {
    if (_mmap) {
      UnmapViewOfFile(_mmap);
    }
    if (_lastpos) {
      UnmapViewOfFile(_lastpos);
    }
    if (_hMapFile) {
      CloseHandle(_hMapFile);
    }
    if (_hLockFile) {
      CloseHandle(_hLockFile);
    }
    if (_hMutex) {
      CloseHandle(_hMutex);
    }
  }

  void writeToFile(char *line) {
    if (!_mmap || !_lastpos || !_hMutex) return;

    // Lock
    DWORD waitResult = WaitForSingleObject(_hMutex, INFINITE);
    if (waitResult != WAIT_OBJECT_0) {
      return;
    }

    size_t len = strlen(line);
    // Use memcpy instead of strncpy to avoid null-padding which would overwrite subsequent samples
    memcpy(_mmap + *_lastpos, line, len);

    // Memory barrier to ensure data is visible to other processes before
    // updating the position counter. Critical for ARM64 where memory ordering
    // is weaker than x86/x64. Without this barrier, readers in other processes
    // may see the updated position but stale/zero data.
    MemoryBarrier();

    *_lastpos += len;

    // Unlock
    ReleaseMutex(_hMutex);
  }

 private:
  // Prevent copying and assignment
  SampleFile(const SampleFile &) = delete;
  SampleFile &operator=(const SampleFile &) = delete;

  void convertToWindowsName(char *name) {
    // Convert "/tmp/scalene-xxx" to "Local\\scalene-xxx"
    // and replace remaining slashes
    char temp[MAX_BUFSIZE];
    const char *src = name;

    // Skip /tmp/ prefix if present
    if (strncmp(src, "/tmp/", 5) == 0) {
      src += 5;
    } else if (src[0] == '/') {
      src += 1;
    }

    snprintf_for_init(temp, MAX_BUFSIZE - 1, "Local\\%s", src);

    // Replace any remaining forward slashes with underscores
    for (char *p = temp; *p; p++) {
      if (*p == '/') *p = '_';
    }

    strncpy(name, temp, MAX_BUFSIZE - 1);
    name[MAX_BUFSIZE - 1] = '\0';
  }

  char _signalname[MAX_BUFSIZE];
  char _lockname[MAX_BUFSIZE];
  char _initname[MAX_BUFSIZE];

  HANDLE _hMapFile = NULL;
  HANDLE _hLockFile = NULL;
  HANDLE _hMutex = NULL;

  char *_mmap = nullptr;
  uint64_t *_lastpos = nullptr;
};

#endif // _WIN32

#endif // SAMPLEFILE_WIN_H
