// Where was the main thread when the CPU timer signal arrived? (issue #466)
//
// CPython runs a Python signal handler only at its next safe point (a
// call's return, a loop back-edge, a function's entry; not after every
// bytecode). A sample that arrives during a bare operator
// (`x @ y` on a line of its own) is therefore handled on the *next* line
// that calls something, and was charged there. The C-level handler that
// timestamps the arrival calls scalene_peek_frame() to record the code
// object and the bytecode offset the thread was executing at that instant;
// the Python handler maps them back to a line.
//
// Its own C extension module (scalene._frame_peek), so that only this code
// sees CPython's internal headers (Py_BUILD_CORE), compiled as C: MSVC
// can't compile them as C++. _scalene_unwind gets scalene_peek_frame from
// the capsule "scalene._frame_peek.peek". Async-signal-safe: only loads, no
// allocation, no locks.
// The result is unvalidated (a frame may be half pushed); the Python side
// only uses it if the code object is still on the thread's stack and the
// offset falls inside it.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdint.h>

#include "frame_peek.h"

#if PY_VERSION_HEX >= 0x030B0000
#ifndef Py_BUILD_CORE
#define Py_BUILD_CORE 1
#endif
#if PY_VERSION_HEX >= 0x030E0000
#include "internal/pycore_interpframe.h"
#else
#include "internal/pycore_frame.h"
#endif
#if PY_VERSION_HEX >= 0x030D0000
#include "internal/pycore_code.h"
#endif
#else
#include <frameobject.h>
#endif

static int scalene_peek_frame(PyThreadState* tstate, uintptr_t* code_out,
                              int* offset_out) {
  if (tstate == NULL) return 0;
#if PY_VERSION_HEX >= 0x030E0000
  struct _PyInterpreterFrame* f = tstate->current_frame;
  if (f == NULL) return 0;
  PyObject* executable = PyStackRef_AsPyObjectBorrow(f->f_executable);
  if (executable == NULL || Py_TYPE(executable) != &PyCode_Type) return 0;
  PyCodeObject* code = (PyCodeObject*)executable;
  const _Py_CODEUNIT* ip = f->instr_ptr;
#elif PY_VERSION_HEX >= 0x030D0000
  struct _PyInterpreterFrame* f = tstate->current_frame;
  if (f == NULL) return 0;
  PyObject* executable = f->f_executable;
  if (executable == NULL || Py_TYPE(executable) != &PyCode_Type) return 0;
  PyCodeObject* code = (PyCodeObject*)executable;
  const _Py_CODEUNIT* ip = f->instr_ptr;
#elif PY_VERSION_HEX >= 0x030B0000
  if (tstate->cframe == NULL) return 0;
  struct _PyInterpreterFrame* f = tstate->cframe->current_frame;
  if (f == NULL) return 0;
  PyCodeObject* code = f->f_code;
  if (code == NULL || Py_TYPE((PyObject*)code) != &PyCode_Type) return 0;
  const _Py_CODEUNIT* ip = f->prev_instr;  // the instruction started last
#else
  PyFrameObject* f = tstate->frame;
  if (f == NULL || f->f_code == NULL || f->f_lasti < 0) return 0;
  *code_out = (uintptr_t)f->f_code;
#if PY_VERSION_HEX >= 0x030A0000
  *offset_out = f->f_lasti * (int)sizeof(_Py_CODEUNIT);  // in instructions
#else
  *offset_out = f->f_lasti;  // in bytes
#endif
  return 1;
#endif
#if PY_VERSION_HEX >= 0x030B0000
  if (ip == NULL) return 0;
  const _Py_CODEUNIT* start = _PyCode_CODE(code);
  if (ip < start) return 0;
  *code_out = (uintptr_t)code;
  *offset_out = (int)((ip - start) * (Py_ssize_t)sizeof(_Py_CODEUNIT));
  return 1;
#endif
}

static struct PyModuleDef frame_peek_module = {
    PyModuleDef_HEAD_INIT, "_frame_peek",
    "Signal-safe peek at a thread's current Python frame (issue #466).", -1,
    NULL,
};

PyMODINIT_FUNC PyInit__frame_peek(void) {
  PyObject* m = PyModule_Create(&frame_peek_module);
  if (m == NULL) return NULL;
  PyObject* capsule = PyCapsule_New((void*)scalene_peek_frame,
                                    SCALENE_FRAME_PEEK_CAPSULE, NULL);
  if (capsule == NULL || PyModule_AddObject(m, "peek", capsule) < 0) {
    Py_XDECREF(capsule);
    Py_DECREF(m);
    return NULL;
  }
#ifdef Py_GIL_DISABLED
  PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED);
#endif
  return m;
}
