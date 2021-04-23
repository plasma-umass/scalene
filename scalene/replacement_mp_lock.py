from scalene.scalene_profiler import Scalene
import sys
import threading
import _multiprocessing
import multiprocessing.synchronize
import os

# The _multiprocessing module is entirely undocumented-- the header of the 
# acquire function is 
# static PyObject * _multiprocessing_SemLock_acquire_impl(SemLockObject *self, int blocking, PyObject *timeout_obj)
#
# timeout_obj is parsed as a double
@Scalene.shim
def replacement_mp_semlock(scalene: Scalene):
    
    class ReplacementSemLock(multiprocessing.synchronize.Lock):
        
        def __enter__(self) -> bool:
            timeout = sys.getswitchinterval()
            tident = threading.get_ident()
            while True:
                scalene.set_thread_sleeping(tident)
                acquired = self._semlock.acquire(timeout=timeout)
                scalene.reset_thread_sleeping(tident)
                if acquired:
                    return True
                
        def __exit__(self, *args) -> None:
            super().__exit__(*args)
            
    multiprocessing.synchronize.Lock = ReplacementSemLock


    
