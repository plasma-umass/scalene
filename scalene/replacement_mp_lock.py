from scalene.scalene_profiler import Scalene
import sys
import threading
import _multiprocessing
import multiprocessing.synchronize

# The _multiprocessing module is entirely undocumented-- the header of the 
# acquire function is 
# static PyObject * _multiprocessing_SemLock_acquire_impl(SemLockObject *self, int blocking, PyObject *timeout_obj)
#
# timeout_obj is parsed as a double
@Scalene.shim
def replacement_mp_semlock(scalene: Scalene):
    if sys.version_info.major == 3 and (sys.version_info.minor >= 9 or (sys.version_info.minor == 8 and sys.version_info.micro >= 9)):
        class ReplacementSemLock(_multiprocessing.SemLock):
            def acquire(self, blocking: bool = True, timeout: float = None):
                print("uwu")
                tident = threading.get_ident()
                start_time = scalene.get_wallclock_time()
                print("IN LOCK")
                if blocking:
                    if timeout is None:
                        timeout = sys.getswitchinterval()
                    else:
                        timeout = min(timeout, sys.getswitchinterval())
                else:
                    timeout = None
            
                while True:
                    scalene.set_thread_sleeping(tident)
                    acquired = super().acquire(blocking, timeout)
                    scalene.reset_thread_sleeping(tident)
                    if acquired:
                        return True
                    if not blocking:
                        return False
                    if timeout:
                        end_time = scalene.get_wallclock_time()
                        if end_time - start_time >= timeout:
                            return False

        _multiprocessing.SemLock = ReplacementSemLock
    else:
        class ReplacementSemLock(multiprocessing.synchronize.SemLock):
            def __enter__(self):
                timeout = sys.getswitchinterval()
                tident = threading.get_ident()
                while True:
                    scalene.set_thread_sleeping(tident)
                    acquired = self._semlock.acquire(blocking=True, timeout=timeout)
                    scalene.reset_thread_sleeping(tident)
                    if acquired:
                        return True
        
        multiprocessing.synchronize.SemLock = ReplacementSemLock


    
