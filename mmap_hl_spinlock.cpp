#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <heaplayers.h>
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

static PyObject* mmap_lock(PyObject* self, PyObject* args) {
    // Casts the pointer at the expected location to a SpinLock and then locks it
    Py_buffer o;
    if(! PyArg_ParseTuple(args, "s*", &o)) // "s*" means readable/writeable buffer as per https://docs.python.org/3/c-api/arg.html
                                           // Buffer protocol is found here https://docs.python.org/3/c-api/buffer.html
        return NULL;
    HL::SpinLock* lock = (HL::SpinLock*) (((char*)o.buf) + sizeof(uint64_t));
    lock->lock();
    Py_RETURN_NONE;
}

static PyObject* mmap_unlock(PyObject* self, PyObject* args) {
    // casts the pointer at the expected location to a SpinLock and then unlocks it
    Py_buffer o;
    if(! PyArg_ParseTuple(args, "s*", &o))
        return NULL;
    HL::SpinLock* lock = (HL::SpinLock*) (((char*)o.buf) + sizeof(uint64_t));
    lock->unlock();
    Py_RETURN_NONE;
}

static PyMethodDef MmapHlSpinlockMethods[] = {
    {"mmap_lock", mmap_lock, METH_VARARGS, "locks HL::SpinLock located in buffer"},
    {"mmap_unlock", mmap_unlock, METH_VARARGS, "unlocks HL::SpinLock located in buffer"}
};

static struct PyModuleDef mmaphlspinlockmodule = {
    PyModuleDef_HEAD_INIT,
    "mmap_hl_spinlock",
    NULL,
    -1, 
    MmapHlSpinlockMethods
};

PyMODINIT_FUNC PyInit_mmap_hl_spinlock(void) {
    return PyModule_Create(&mmaphlspinlockmodule);
}