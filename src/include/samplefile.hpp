#pragma once
#ifndef SAMPLEFILE_H
#define SAMPLEFILE_H

#include <errno.h>
#include <heaplayers.h>

#if !defined(_WIN32)
#include <pthread.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <unistd.h>
#else
#include <sys/stat.h>
#define S_IRUSR _S_IRUSR
#define S_IWUSR _S_IWUSR
#endif

#include "printf.h"
#include "rtememcpy.h"

// Handles creation, deletion, and concurrency control
// signal files in memory

class SampleFile {
 public:
  static constexpr int MAX_BUFSIZE =
      256;  // actual (and maximum) length of a line passed to writeToFile
 private:
  static constexpr int LOCK_FD_SIZE = 4096;
  static constexpr int MAX_FILE_SIZE = 4096 * 65536;

  static char *initializer;

 public:
  SampleFile(char *filename_template, char *lockfilename_template,
             char *init_template) {
    static uint base_pid = getpid();
    constexpr int FILENAME_LENGTH = 255;
    snprintf(_init_filename, FILENAME_LENGTH - 1, init_template, base_pid);
    snprintf(_signalfile, FILENAME_LENGTH - 1, filename_template, base_pid);
    snprintf(_lockfile, FILENAME_LENGTH - 1, lockfilename_template, base_pid);
    int signal_fd = open(_signalfile, flags, perms);
    int lock_fd = open(_lockfile, flags, perms);
    if ((signal_fd == -1) || (lock_fd == -1)) {
      fprintf(stderr, "Scalene: internal error = %d (%s:%d)\n", errno, __FILE__,
              __LINE__);
      abort();
    }
    if (ftruncate(signal_fd, MAX_FILE_SIZE) != 0) {
      fprintf(stderr, "Scalene: internal error = %d (%s:%d)\n", errno, __FILE__,
              __LINE__);
      abort();
    }
    if (ftruncate(lock_fd, LOCK_FD_SIZE) != 0) {
      fprintf(stderr, "Scalene: internal error = %d (%s:%d)\n", errno, __FILE__,
              __LINE__);
      abort();
    }
    _mmap = reinterpret_cast<char *>(mmap(
        0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, signal_fd, 0));
    _lastpos = reinterpret_cast<uint64_t *>(
        mmap(0, LOCK_FD_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, lock_fd, 0));
    close(signal_fd);
    close(lock_fd);
    if (_mmap == MAP_FAILED) {
      fprintf(stderr, "Scalene: internal error = %d (%s:%d)\n", errno, __FILE__,
              __LINE__);
      abort();
    }
    if (_lastpos == MAP_FAILED) {
      fprintf(stderr, "Scalene: internal error = %d (%s:%d)\n", errno, __FILE__,
              __LINE__);
      abort();
    }
    // This is a miserable hack that does not deserve to exist
    int init_fd = open(_init_filename, O_CREAT | O_RDWR, perms);
    int res = flock(init_fd, LOCK_EX);
    char buf[4];
    memset(buf, 0, 4);
    // A samplefile may be initialized
    // multiple times from the same template,
    // so access must be synchronized.
    // the corresponding file/memory regions
    // have been initialized,
    // the lockfile will have the string "q&"
    // at the beginning. Otherwise, it is written after initialization
    //
    // 3 bytes are read to bring in both the magic string and the end-of-string
    // character "q&\0"
    // fsync(init_fd);

    int amt_read = read(init_fd, buf, 3);
    if (amt_read != 0 && strcmp(buf, "q&") == 0) {
      // If magic number is present, we know that a HL::SpinLock has already
      // been initialized
      _spin_lock = (HL::SpinLock *)(((char *)_lastpos) + sizeof(uint64_t));
    } else {
      if (write(init_fd, "q&", 3) != 3) {
        fprintf(stderr, "Scalene: internal error = %d (%s:%d)\n", errno, __FILE__,
                __LINE__);
        abort();
      }
      fsync(init_fd);
      _spin_lock = new (((char *)_lastpos) + sizeof(uint64_t)) HL::SpinLock();
      *_lastpos = 0;
    }

    flock(init_fd, LOCK_UN);
    close(init_fd);
  }
  ~SampleFile() {
    munmap(_mmap, MAX_FILE_SIZE);
    munmap(_lastpos, LOCK_FD_SIZE);
    //unlink(_signalfile);
    // unlink(_lockfile);
    unlink(_init_filename);
  }
  void writeToFile(char *line, int is_malloc) {
    _spin_lock->lock();
    char *ptr = _mmap;
    strncpy(_mmap + *_lastpos, (const char *)line, MAX_BUFSIZE);

    *_lastpos += strlen(_mmap + *_lastpos) - 1;
    _spin_lock->unlock();
  }

 private:
  // Prevent copying and assignment.
  SampleFile(const SampleFile &) = delete;
  SampleFile &operator=(const SampleFile &) = delete;

  // Flags for the mmap regions
  static constexpr auto flags = O_RDWR | O_CREAT;
  static constexpr auto perms = S_IRUSR | S_IWUSR;

  char
      _signalfile[MAX_BUFSIZE];  // Name of log file that signals are written to
  char _lockfile[MAX_BUFSIZE];   // Name of file that _lastpos is persisted in
  char _init_filename[MAX_BUFSIZE];  // initializer filename
  char *_mmap;                       // address of first byte of log
  uint64_t *_lastpos;                // address of first byte of _lastpos
  HL::SpinLock *_spin_lock;
};

#endif
