#pragma once
#ifndef SAMPLEFILE_H
#define SAMPLEFILE_H

#include <heaplayers.h>
#include <pthread.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <unistd.h>
#include <errno.h>

#include "rtememcpy.h"
#include "stprintf.h"
#include "tprintf.h"

// Handles creation, deletion, and concurrency control
// signal files in memory

class SampleFile {
 public:
  static constexpr int MAX_BUFSIZE =
      256;  // actual (and maximum) length of a line passed to writeToFile
 private:
  static constexpr int LOCK_FD_SIZE = 4096;
  static constexpr int MAX_FILE_SIZE = 4096 * 65536;

  static char* initializer;
public:
  SampleFile(char* filename_template, char* lockfilename_template, char* init_template) {
    static uint base_pid = getpid();
    static HL::PosixLock init_lock;
    char init_file[64];
    stprintf::stprintf(init_file, init_template, base_pid);
    stprintf::stprintf(_signalfile, filename_template, base_pid);
    stprintf::stprintf(_lockfile, lockfilename_template, base_pid);
    int signal_fd = open(_signalfile, flags, perms);
    int lock_fd = open(_lockfile, flags, perms);
    if ((signal_fd == -1) || (lock_fd == -1)) {
      tprintf::tprintf("Scalene: internal error = @ (@:@)\n", errno, __FILE__,
                       __LINE__);
      abort();
    }
    ftruncate(signal_fd, MAX_FILE_SIZE);
    ftruncate(lock_fd, 4096);
    _mmap = reinterpret_cast<char *>(mmap(
        0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, signal_fd, 0));
    _lastpos = reinterpret_cast<uint64_t *>(
        mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, lock_fd, 0));
    close(signal_fd);
    close(lock_fd);
    if (_mmap == MAP_FAILED) {
      tprintf::tprintf("Scalene: internal error = @ (@:@)\n", errno, __FILE__,
                       __LINE__);
      abort();
    }
    if (_lastpos == MAP_FAILED) {
      tprintf::tprintf("Scalene: internal error = @ (@:@)\n", errno, __FILE__,
                       __LINE__);
      abort();
    }
    // This is a miserable hack that does not deserve to exist
    int init_fd = open(init_file, O_CREAT|O_RDWR, perms);
    int res = flock(init_fd, LOCK_EX);
    char buf[3];
    int amt_read = read(init_fd, buf, 3);
    if (amt_read != 0 && strcmp(buf, "q&") == 0) {
      // If magic number is present, we know that a HL::SpinLock has already been initialized
      _spin_lock = (HL::SpinLock*) (((char*) _lastpos) + sizeof(uint64_t));
    } else {
      write(init_fd, "q&", 3);
      _spin_lock = new(((char*) _lastpos )+ sizeof(uint64_t)) HL::SpinLock();
      *_lastpos = 0;
    }

    flock(init_fd, LOCK_UN);
    close(init_fd);
  }
  ~SampleFile() {
    munmap(_mmap, MAX_FILE_SIZE);
    munmap(_lastpos, LOCK_FD_SIZE);
    unlink(_signalfile);
    unlink(_lockfile);
    //    tprintf::tprintf("~SampleFile: pid = @, tid=@, this=@\n", getpid(),
    //    pthread_self(), (void*) this);
  }
  void writeToFile(char* line, int is_malloc) {
    _spin_lock->lock();
    char* ptr = _mmap;
    strncpy(_mmap + *_lastpos, (const char *) line, MAX_BUFSIZE); 
    *_lastpos += strlen(_mmap + *_lastpos) - 1;
    _spin_lock->unlock();
    // tprintf::tprintf("Unlocked C @\n", getpid());
  }

 private:
  // Prevent copying and assignment.
  SampleFile(const SampleFile &) = delete;
  SampleFile &operator=(const SampleFile &) = delete;

  // Flags for the mmap regions
  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;

  char _signalfile[256];  // Name of log file that signals are written to
  char _lockfile[256];    // Name of file that _lastpos is persisted in
  char *_mmap;            // address of first byte of log
  uint64_t *_lastpos;     // address of first byte of _lastpos
  HL::SpinLock *_spin_lock;
  // Note: initialized in libscalene.cpp
  static HL::PosixLock lock;
  // static char* initializer;
};

#endif
