#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <heaplayers.h>
#include <string.h>

#include <mutex>

// This uses Python's buffer interface to view a mmap buffer passed in,
// which we assume has a layout of [ uint64_t | HL::SpinLock ].
//
// We assume that the lock region has been fully initialized at this point,
// since initialization occurs at the bootstrapping of the per-thread heap
//
// This is derived in part from
// https://docs.python.org/3/extending/extending.html
//
// FIXME: Encapsulate under scalene namespace
// TODO: Wrap in Python library with ContextManager

static PyObject* get_line_atomic(PyObject* self, PyObject* args) {
  // Casts the pointer at the expected location to a SpinLock and then locks it
  Py_buffer lock_mmap;
  Py_buffer signal_mmap;
  Py_buffer result_bytearray;
  Py_buffer lastpos_buf;
  if (!PyArg_ParseTuple(
          args, "s*s*s*s*", &lock_mmap, &signal_mmap, &result_bytearray,
          &lastpos_buf))  // "s*" means readable/writeable buffer as per
                          // https://docs.python.org/3/c-api/arg.html Buffer
                          // protocol is found here
                          // https://docs.python.org/3/c-api/buffer.html
    return NULL;
  auto buf = reinterpret_cast<char*>(lock_mmap.buf) + sizeof(uint64_t);
  auto lock = reinterpret_cast<HL::SpinLock*>(buf);

  std::lock_guard<HL::SpinLock> theLock(*lock);

  auto lastpos = reinterpret_cast<uint64_t*>(lastpos_buf.buf);
  auto current_iter = reinterpret_cast<char*>(signal_mmap.buf) + *lastpos;
  auto start = current_iter;
  auto result_iter = reinterpret_cast<char*>(result_bytearray.buf);

  if (*current_iter == '\n') {
    Py_RETURN_FALSE;
  } else {
    auto null_loc = reinterpret_cast<char*>(
        memchr(current_iter, '\n', result_bytearray.len));
    for (int i = 0; i <= null_loc - start; i++) {
      *(result_iter++) = *(current_iter++);
      (*lastpos)++;
    }
  }

  Py_RETURN_TRUE;
}

static PyMethodDef MmapHlSpinlockMethods[] = {
    {"get_line_atomic", get_line_atomic, METH_VARARGS,
     "locks HL::SpinLock located in buffer"},
    {NULL, NULL, 0, NULL}};

static struct PyModuleDef mmaphlspinlockmodule = {
    PyModuleDef_HEAD_INIT, "get_line_atomic", NULL, -1, MmapHlSpinlockMethods};

PyMODINIT_FUNC PyInit_get_line_atomic(void) {
  return PyModule_Create(&mmaphlspinlockmodule);
}
