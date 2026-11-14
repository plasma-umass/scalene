// Where was the main thread when the CPU timer signal arrived? (issue #466)
//
// CPython runs a Python signal handler only at its next safe point: on 3.10+
// that is a call's return, a loop back-edge, or a function's entry, not
// after every bytecode. A sample that arrives during a bare operator
// (`x @ y` on a line of its own) is therefore handled on the *next* line
// that calls something, and was charged there. The C-level handler that
// timestamps the arrival calls scalene_peek_frame() to record the code
// object and the bytecode offset the thread was executing at that instant;
// the Python handler maps them back to a line.
//
// Kept in its own file so that only this code sees CPython's internal
// headers (Py_BUILD_CORE). Async-signal-safe: only loads, no allocation, no
// locks.
// The result is unvalidated (a frame may be half pushed); the Python side
// only uses it if the code object is still on the thread's stack and the
// offset falls inside it.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cstdint>

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
#elif PY_VERSION_HEX >= 0x030A0000
#include <frameobject.h>
#endif

extern "C" int scalene_peek_frame(PyThreadState* tstate, uintptr_t* code_out,
                                  int* offset_out) {
  if (tstate == nullptr) return 0;
#if PY_VERSION_HEX >= 0x030E0000
  struct _PyInterpreterFrame* f = tstate->current_frame;
  if (f == nullptr) return 0;
  PyObject* executable = PyStackRef_AsPyObjectBorrow(f->f_executable);
  if (executable == nullptr || Py_TYPE(executable) != &PyCode_Type) return 0;
  PyCodeObject* code = reinterpret_cast<PyCodeObject*>(executable);
  const _Py_CODEUNIT* ip = f->instr_ptr;
#elif PY_VERSION_HEX >= 0x030D0000
  struct _PyInterpreterFrame* f = tstate->current_frame;
  if (f == nullptr) return 0;
  PyObject* executable = f->f_executable;
  if (executable == nullptr || Py_TYPE(executable) != &PyCode_Type) return 0;
  PyCodeObject* code = reinterpret_cast<PyCodeObject*>(executable);
  const _Py_CODEUNIT* ip = f->instr_ptr;
#elif PY_VERSION_HEX >= 0x030B0000
  if (tstate->cframe == nullptr) return 0;
  struct _PyInterpreterFrame* f = tstate->cframe->current_frame;
  if (f == nullptr) return 0;
  PyCodeObject* code = f->f_code;
  if (code == nullptr || Py_TYPE(reinterpret_cast<PyObject*>(code)) != &PyCode_Type) return 0;
  const _Py_CODEUNIT* ip = f->prev_instr;  // the instruction started last
#elif PY_VERSION_HEX >= 0x030A0000
  PyFrameObject* f = tstate->frame;
  if (f == nullptr || f->f_code == nullptr) return 0;
  *code_out = reinterpret_cast<uintptr_t>(f->f_code);
  *offset_out = f->f_lasti * static_cast<int>(sizeof(_Py_CODEUNIT));  // in instructions
  return f->f_lasti >= 0;
#else
  // Before 3.10, CPython checks for signals after almost every bytecode, so
  // the handler's own frame already shows the right line.
  (void)code_out;
  (void)offset_out;
  return 0;
#endif
#if PY_VERSION_HEX >= 0x030B0000
  if (ip == nullptr) return 0;
  const _Py_CODEUNIT* start = _PyCode_CODE(code);
  if (ip < start) return 0;
  *code_out = reinterpret_cast<uintptr_t>(code);
  *offset_out = static_cast<int>((ip - start) * static_cast<Py_ssize_t>(sizeof(_Py_CODEUNIT)));
  return 1;
#endif
}
