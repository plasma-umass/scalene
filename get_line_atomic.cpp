#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <heaplayers.h>
#include <string.h>
#include "tprintf.h"
// This uses Python's buffer interface to view a mmap buffer passed in, 
// which we assume has a layout of [ uint64_t | HL::SpinLock ]. 
//
// We assume that the lock region has been fully initialized at this point,
// since initialization occurs at the bootstrapping of the per-thread heap
//
// This is derived in part from https://docs.python.org/3/extending/extending.html
//
// FIXME: Encapsulate under scalene namespace
// TODO: Wrap in Python library with ContextManager


static PyObject* get_line_atomic(PyObject* self, PyObject* args) {
    // Casts the pointer at the expected location to a SpinLock and then locks it
    Py_buffer lock_mmap;
    Py_buffer signal_mmap;
    Py_buffer result_bytearray;
    Py_buffer lastpos_buf;
    if(! PyArg_ParseTuple(args, "s*s*s*s*", &lock_mmap, &signal_mmap, &result_bytearray, &lastpos_buf)) // "s*" means readable/writeable buffer as per https://docs.python.org/3/c-api/arg.html
                                                                                                        // Buffer protocol is found here https://docs.python.org/3/c-api/buffer.html
        return NULL;
    HL::SpinLock* lock = (HL::SpinLock*) (((char*)lock_mmap.buf) + sizeof(uint64_t));
    // tprintf::tprintf("Locking python @\n", getpid());
    lock->lock();

    uint64_t* lastpos = (uint64_t*) lastpos_buf.buf;
    char* current_iter = ((char*) signal_mmap.buf) + *lastpos;
    char* start = current_iter;
    char* result_iter = (char*) result_bytearray.buf;

    if (*current_iter == '\n') {
        // (*lastpos)--;
        lock->unlock();
        Py_RETURN_FALSE;
    } else {
        char* null_loc = (char*) memchr(current_iter, '\n', result_bytearray.len);
        for(int i = 0; i <= null_loc - start; i++) {
            *(result_iter++) = *(current_iter++); 
            (*lastpos)++;
        }
        // (*lastpos)++;
    }
    
    lock->unlock();
    Py_RETURN_TRUE;
}



static PyMethodDef MmapHlSpinlockMethods[] = {
    {"get_line_atomic", get_line_atomic, METH_VARARGS, "locks HL::SpinLock located in buffer"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef mmaphlspinlockmodule = {
    PyModuleDef_HEAD_INIT,
    "get_line_atomic",
    NULL,
    -1, 
    MmapHlSpinlockMethods
};

PyMODINIT_FUNC PyInit_get_line_atomic(void) {
    return PyModule_Create(&mmaphlspinlockmodule);
}