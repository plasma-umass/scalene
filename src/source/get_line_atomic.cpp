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

namespace {
// Releases a Py_buffer obtained via PyArg_ParseTuple("s*") on scope exit.
// Without this, every call leaked a buffer export on each argument (which,
// among other things, keeps the mmap objects from ever being closed).
struct BufferGuard {
  Py_buffer view;
  bool held = false;
  ~BufferGuard() {
    if (held) PyBuffer_Release(&view);
  }
};
}  // namespace

static PyObject* get_line_atomic(PyObject* self, PyObject* args) {
  BufferGuard lock_mmap, signal_mmap, result_bytearray, lastpos_buf;
  if (!PyArg_ParseTuple(
          args, "s*s*s*s*", &lock_mmap.view, &signal_mmap.view,
          &result_bytearray.view,
          &lastpos_buf.view))  // "s*" means readable/writeable buffer as per
                               // https://docs.python.org/3/c-api/arg.html
                               // Buffer protocol is found here
                               // https://docs.python.org/3/c-api/buffer.html
    return NULL;
  lock_mmap.held = signal_mmap.held = result_bytearray.held =
      lastpos_buf.held = true;

  using LockType = HL::SpinLock;
  if (lock_mmap.view.len <
          static_cast<Py_ssize_t>(sizeof(uint64_t) + sizeof(LockType)) ||
      lastpos_buf.view.len < static_cast<Py_ssize_t>(sizeof(uint64_t))) {
    PyErr_SetString(PyExc_ValueError,
                    "get_line_atomic: lock or lastpos buffer too small");
    return NULL;
  }
  if (result_bytearray.view.readonly) {
    PyErr_SetString(PyExc_ValueError,
                    "get_line_atomic: result buffer must be writable");
    return NULL;
  }

  auto buf = reinterpret_cast<char*>(lock_mmap.view.buf) + sizeof(uint64_t);
  auto lock = reinterpret_cast<LockType*>(buf);

  std::lock_guard<LockType> theLock(*lock);

  auto lastpos = reinterpret_cast<uint64_t*>(lastpos_buf.view.buf);
  const auto signal_len = static_cast<uint64_t>(signal_mmap.view.len);
  if (*lastpos >= signal_len) {
    // Nothing left to read (or a corrupt position): never index past the
    // end of the signal buffer (issue #1117).
    Py_RETURN_FALSE;
  }

  auto current_iter = reinterpret_cast<char*>(signal_mmap.view.buf) + *lastpos;
  auto start = current_iter;
  auto result_iter = reinterpret_cast<char*>(result_bytearray.view.buf);

  // Bound the newline search by BOTH the bytes remaining in the signal buffer
  // and the capacity of the result buffer. The search used to be bounded only
  // by the result buffer's size, so with lastpos near the end of the mapping
  // memchr read past it (SIGBUS/SIGSEGV, or garbage from adjacent memory;
  // issue #1117). Limiting it to the result capacity also guarantees that the
  // line plus its newline (len + 1 bytes) fits in the result buffer.
  const uint64_t remaining = signal_len - *lastpos;
  const auto capacity = static_cast<uint64_t>(result_bytearray.view.len);
  const size_t search_len =
      static_cast<size_t>(remaining < capacity ? remaining : capacity);

  char* nl = reinterpret_cast<char*>(memchr(current_iter, '\n', search_len));
  size_t len = (nl == nullptr) ? 0 : static_cast<size_t>(nl - start);

  if (len == 0) {
    Py_RETURN_FALSE;
  }

#if 0
  char tmp[result_bytearray.view.len+1];
  memcpy(tmp, current_iter, len);
  tmp[len] = '\0';
  tprintf::tprintf("read @ from @\n", tmp, *lastpos);
#endif

  // avoid 'memcpy', as Scalene interposes on it to measure memory copying
  for (size_t i = 0; i <= len; i++) {
    *(result_iter++) = *(current_iter++);
  }

  *lastpos += len + 1;

  Py_RETURN_TRUE;
}

static PyMethodDef MmapHlSpinlockMethods[] = {
    {"get_line_atomic", get_line_atomic, METH_VARARGS,
     "locks a mutex located in buffer"},
    {NULL, NULL, 0, NULL}};

static struct PyModuleDef mmaphlspinlockmodule = {
    PyModuleDef_HEAD_INIT, "get_line_atomic", NULL, -1, MmapHlSpinlockMethods};

PyMODINIT_FUNC PyInit_get_line_atomic(void) {
  PyObject* m = PyModule_Create(&mmaphlspinlockmodule);
#ifdef Py_GIL_DISABLED
  if (m != NULL) {
    PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED);
  }
#endif
  return m;
}
