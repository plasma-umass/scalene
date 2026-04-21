"""
PyTorch-flavored reproducer for scalene issues #857 / #659.

A threading.Thread worker runs a loop of large torch.mm matmuls and
fresh-tensor allocations. PyTorch's intraop thread pool farms the matmul out
to worker threads that PyTorch itself spawned at import time (pthreads with
no PyThreadState). Those pool workers may also allocate scratch buffers.

If those pool threads allocate, scalene on master would attribute their
bytes to whichever Python line the main/worker thread was on at sample
time. After the fix, such allocations go to the <native> bucket.
"""

import os
import threading
import time

# Keep torch's intraop pool active — force at least a few pool threads.
os.environ.setdefault("OMP_NUM_THREADS", "4")

import torch


def worker() -> None:
    torch.set_num_threads(4)
    for _ in range(64):
        a = torch.randn(1024, 1024, dtype=torch.float32)  # ~4 MB
        b = torch.randn(1024, 1024, dtype=torch.float32)  # ~4 MB
        c = torch.mm(a, b)                                 # ~4 MB, dispatches to pool
        _ = c.sum().item()                                 # force materialization
        del a, b, c


def main() -> None:
    t = threading.Thread(target=worker)
    t.start()
    # Main-thread sleep. With the bug in #659, this line would be charged
    # with large GB-scale attribution. With the fix and/or a correctly-
    # behaving allocator path, it should be ~0.
    time.sleep(2.0)
    t.join()


if __name__ == "__main__":
    main()
