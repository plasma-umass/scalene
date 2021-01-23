#pragma once
#ifndef SAMPLEFILE_H
#define SAMPLEFILE_H

#include <sys/file.h>
#include <sys/mman.h>
#include <unistd.h>
#include <pthread.h>
#include <heaplayers.h>

#include "tprintf.h"
#include "stprintf.h"
#include "rtememcpy.h"

// Handles creation, deletion, and concurrency control
// signal files in memory

class SampleFile {
  static constexpr int LOCK_FD_SIZE = 4096;
  static constexpr int MAX_FILE_SIZE = 4096 * 65536;
  static constexpr int MAX_BUFSIZE = 1024;

public:
  SampleFile(char* filename_template, char* lockfilename_template) {
    auto pid = getpid();
    // tprintf::tprintf("SampleFile: pid = @, tid=@, this=@\n", pid, pthread_self(), (void*) this);
    stprintf::stprintf(_signalfile, filename_template, pid);
    stprintf::stprintf(_lockfile, lockfilename_template, pid);
    int signal_fd = open(_signalfile, flags, perms);
    int lock_fd = open(_lockfile, flags, perms);
    if ((signal_fd == -1) || (lock_fd == -1)) {
      tprintf::tprintf("Scalene: internal error = @ (@:@)\n", errno, __FILE__, __LINE__);
      abort();
    }
    ftruncate(signal_fd, MAX_FILE_SIZE);
    ftruncate(lock_fd, LOCK_FD_SIZE);
    _mmap = reinterpret_cast<char*>(mmap(0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, signal_fd, 0));
    _lastpos = reinterpret_cast<int*>(mmap(0, LOCK_FD_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, lock_fd, 0));
    close(signal_fd);
    close(lock_fd);
    if (_mmap == MAP_FAILED) {
      tprintf::tprintf("Scalene: internal error = @ (@:@)\n", errno, __FILE__, __LINE__);
      abort();
    }
    if (_lastpos == MAP_FAILED) {
      tprintf::tprintf("Scalene: internal error = @ (@:@)\n", errno, __FILE__, __LINE__);
      abort();
    }
    *_lastpos = 0;
  }
  ~SampleFile() {
    munmap(_mmap, MAX_FILE_SIZE);
    munmap(_lastpos, LOCK_FD_SIZE);
    unlink(_signalfile);
    unlink(_lockfile);
    //    tprintf::tprintf("~SampleFile: pid = @, tid=@, this=@\n", getpid(), pthread_self(), (void*) this);
  }
  void writeToFile(char* line) {
    lock.lock();
    strncpy(_mmap + *_lastpos, (const char *) line, MAX_BUFSIZE); // FIXME
    *_lastpos += strlen(_mmap + *_lastpos) - 1;
    lock.unlock();
  }

private:

  // Prevent copying and assignment.
  SampleFile(const SampleFile&) = delete;
  SampleFile& operator=(const SampleFile&) = delete;
  
  // Flags for the mmap regions
  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;
        
  char _signalfile[256]; // Name of log file that signals are written to
  char _lockfile[256]; // Name of file that _lastpos is persisted in
  //  int _signal_fd; // fd of log file that signals are written to
  //  int _lock_fd; // fd of file that _lastpos is persisted in
  char* _mmap; // address of first byte of log
  int* _lastpos; // address of first byte of _lastpos

  // Note: initialized in libscalene.cpp
  static HL::PosixLock lock;
};

#endif
