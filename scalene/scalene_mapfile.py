import mmap
import os

from typing import NewType, TextIO
Filename = NewType("Filename", str)

class ScaleneMapFile:

    # Things that need to be in sync with the C++ side
    # (see include/sampleheap.hpp, include/samplefile.hpp)
    
    MAX_BUFSIZE = 256  # Must match SampleFile::MAX_BUFSIZE

    def __init__(self, name: str) -> None:
        self.name = name
        self.buf = bytearray(ScaleneMapFile.MAX_BUFSIZE)
        #   file to communicate samples (+ PID)
        self.signal_filename = Filename(
            f"/tmp/scalene-{name}-signal{os.getpid()}"
        )
        self.lock_filename = Filename(f"/tmp/scalene-{name}-lock{os.getpid()}")
        self.init_filename = Filename(f"/tmp/scalene-{name}-init{os.getpid()}")
        self.signal_position = 0
        self.lastpos = bytearray(8)
        self.signal_mmap = None
        self.lock_mmap : mmap.mmap
        self.signal_fd : TextIO
        self.lock_fd : TextIO
        self.signal_fd = open(self.signal_filename, "r")
        os.unlink(self.signal_fd.name)
        self.lock_fd = open(self.lock_filename, "r+")
        os.unlink(self.lock_fd.name)
        self.signal_mmap = mmap.mmap(
            self.signal_fd.fileno(),
            0,
            mmap.MAP_SHARED,
            mmap.PROT_READ,
        )
        self.lock_mmap = mmap.mmap(
            self.lock_fd.fileno(),
            0,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
        )

    def close(self) -> None:
        self.signal_fd.close()
        self.lock_fd.close()
        
