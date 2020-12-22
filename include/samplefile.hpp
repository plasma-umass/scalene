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

    public:
        SampleFile(char* filename_template, char* lockfilename_template) {
            auto pid = getpid();
            stprintf::stprintf(_signalfile, filename_template, pid);
            stprintf::stprintf(_lockfile, lockfilename_template, pid);
            _signal_fd = open(_signalfile, flags, perms);
            _lock_fd = open(_lockfile, flags, perms);
            ftruncate(_signal_fd, MAX_FILE_SIZE);
            _mmap = reinterpret_cast<char*>(mmap(0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, _signal_fd, 0));
            _lastpos = reinterpret_cast<int*>(mmap(0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_ANONYMOUS, _lock_fd, 0));
            *_lastpos = 0;
            if (_mmap == MAP_FAILED) {
                tprintf::tprintf("Scalene: internal error = @\n", errno);
                abort();
            }
            if (_lastpos == MAP_FAILED) {
                tprintf::tprintf("Scalene: internal error = @\n", errno);
                abort();
            }
        }
        ~SampleFile() {
            unlink(_signalfile);
            unlink(_lockfile);
        }
        void writeToFile(char* line) {
            lock.lock();
            rte_memcpy(_mmap + *_lastpos,
                line,
                MAX_BUFSIZE);
            *_lastpos += strlen(_mmap + *_lastpos) - 1;
            lock.unlock();
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
        int* _lastpos; // address of first byte of _lastpos

        // Note: initialized in libscalene.cpp
        static HL::PosixLock lock;
};

#endif