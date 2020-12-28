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

const int MAX_BUFSIZE = 1024;

// Handles creation, deletion, and concurrency control
// signal files in memory

class SampleFile {
  static constexpr int MAX_FILE_SIZE = 4096 * 65536;
  static char* initializer;
public:
  SampleFile(char* filename_template, char* lockfilename_template) {
    // tprintf::tprintf("Starting\n");
    auto pid = getpid();
    stprintf::stprintf(_signalfile, filename_template, pid);
    stprintf::stprintf(_lockfile, lockfilename_template, pid);
    _signal_fd = open(_signalfile, flags, perms);
    _lock_fd = open(_lockfile, flags, perms);
    ftruncate(_signal_fd, MAX_FILE_SIZE);
    ftruncate(_lock_fd, 4096);
    _mmap = reinterpret_cast<char*>(mmap(0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, _signal_fd, 0));
    _lastpos = reinterpret_cast<uint64_t*>(mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, _lock_fd, 0));
    if (_mmap == MAP_FAILED) {
      tprintf::tprintf("Scalene: internal error = @\n", errno);
      abort();
    }
    if (_lastpos == MAP_FAILED) {
      tprintf::tprintf("Scalene: internal error = @\n", errno);
      abort();
    }
    // This is a miserable hack that does not deserve to exist
    int init_fd = open(initializer, O_RDWR, perms);
    int res = flock(init_fd, LOCK_EX);
    char buf[3];
    int amt_read = read(init_fd, buf, 3);
    if (amt_read == 2 && strcmp(buf, "q&") == 0) {
      // If magic number is present, we know that a HL::SpinLock has already been initialized
      _spin_lock = (HL::SpinLock*) (_lastpos + sizeof(uint64_t));
    } else {
      write(init_fd, "q&", 3);
      _spin_lock = new(_lastpos + sizeof(uint64_t)) HL::SpinLock();
      _spin_lock->lock();
      _spin_lock->unlock();
      *_lastpos = 0;

    }
    
    flock(init_fd, LOCK_UN);
    close(init_fd);
  }
  ~SampleFile() {
    unlink(_signalfile);
    unlink(_lockfile);
  }
  void writeToFile(char* line) {
    _spin_lock->lock();
    strncpy(_mmap + *_lastpos, (const char *) line, MAX_BUFSIZE); // FIXME
    *_lastpos += strlen(_mmap + *_lastpos) - 1;
    _spin_lock->unlock();
  }

private:
  // Flags for the mmap regions
  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;
        
  char _signalfile[256]; // Name of log file that signals are written to
  char _lockfile[256]; // Name of file that _lastpos is persisted in
  int _signal_fd; // fd of log file that signals are written to
  int _lock_fd; // fd of file that _lastpos is persisted in
  char* _mmap; // address of first byte of log
  uint64_t* _lastpos; // address of first byte of _lastpos
  HL::SpinLock* _spin_lock;
  // Note: initialized in libscalene.cpp
  static HL::PosixLock lock;
  // static char* initializer;
};

#endif
