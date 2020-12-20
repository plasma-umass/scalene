#ifndef SAMPLEFILE_H
#define SAMPLEFILE_H

#include <sys/file.h>
#include <sys/mman.h>
#include <unistd.h>


#include "tprintf.h"
#include "stprintf.h"

template<int MAX_BUFFSIZE>
class SampleFile {
        static constexpr int MAX_FILE_SIZE = 4096 * 65536;

    public:
        SampleFile(char* filename_template) {
            auto pid = getpid();
            stprintf::stprintf(_signalfile, filename_template, pid);
            _fd = open(_signalfile, flags, perms);
            ftruncate(_fd, MAX_FILE_SIZE);
            _mmap = reinterpret_cast<char*>(mmap(0, MAX_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, _fd, 0))
            if (_mmap == MAP_FAILED) {
                tprintf::tprintf("Scalene: internal error = @\n", errno);
                abort();
            }
        }
        ~SampleFile() {
            unlink(_signalfile);
        }
        void writeToFile(char* line) {
            snprintf(_mmap + _lastpos,
                MAX_BUFFSIZE,
                line);
            _lastpos += strlen(_mmap + _lastpos - 1);
        }

    private:
        static constexpr auto flags = O_RDWR | O_CREAT;
        static constexpr auto perms = S_IRUSR | S_IWUSR;

        char[256] _signalfile;
        int _fd;
        char* _mmap;
        int _lastpos;
};

#endif