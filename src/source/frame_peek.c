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
//
// Nothing read from a frame may be dereferenced directly: the signal can
// land while the frame chain is being updated. On 3.11/3.12,
// _PyEval_EvalFrameDefault publishes its new _PyCFrame (tstate->cframe)
// before setting its current_frame, so for a few instructions that field
// holds leftover stack data -- under the pytest plugin, whose
// sys.monitoring callbacks enter the eval loop constantly, it pointed at
// None and following it crashed the process. So every read through a
// pointer that came from the frame chain goes through safe_copy(), which
// fails instead of faulting.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdint.h>

#include "frame_peek.h"

#include <stddef.h>
#include <string.h>

#if defined(_MSC_VER)
#include <excpt.h>
#elif defined(__linux__)
#include <errno.h>
#include <sys/uio.h>
#include <unistd.h>
#elif defined(__APPLE__)
#include <mach/mach.h>
#include <mach/mach_vm.h>
#endif

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

// Copies n bytes from src, which may be any address. Returns 1 if they were
// all readable, else 0, without faulting. Async-signal-safe.
static int safe_copy(void* dst, const void* src, size_t n) {
  if (src == NULL) return 0;
#if defined(_MSC_VER)
  // scalene_peek_frame catches access violations around the whole peek.
  memcpy(dst, src, n);
  return 1;
#elif defined(__linux__)
  // A process may always read its own memory this way; a bad address is
  // EFAULT. If the call itself is unavailable (ENOSYS, or EPERM under a
  // seccomp filter), give up on locations rather than read unsafely.
  static volatile int unavailable = 0;
  if (unavailable) return 0;
  struct iovec local = {dst, n};
  struct iovec remote = {(void*)src, n};
  int saved_errno = errno;
  ssize_t got = process_vm_readv(getpid(), &local, 1, &remote, 1, 0);
  if (got < 0 && errno != EFAULT) unavailable = 1;
  errno = saved_errno;
  return got == (ssize_t)n;
#elif defined(__APPLE__)
  mach_vm_size_t got = 0;
  kern_return_t kr =
      mach_vm_read_overwrite(mach_task_self(), (mach_vm_address_t)(uintptr_t)src,
                             n, (mach_vm_address_t)(uintptr_t)dst, &got);
  return kr == KERN_SUCCESS && got == n;
#else
  (void)dst;
  (void)n;
  return 0;  // no safe way to read: no locations
#endif
}

static int is_code(PyObject* obj) {
  PyTypeObject* type = NULL;
  return obj != NULL && safe_copy(&type, &obj->ob_type, sizeof(type)) &&
         type == &PyCode_Type;
}

static int peek_frame(PyThreadState* tstate, uintptr_t* code_out,
                      int* offset_out) {
  if (tstate == NULL) return 0;
#if PY_VERSION_HEX >= 0x030B0000
  struct _PyInterpreterFrame* fp = NULL;
#if PY_VERSION_HEX >= 0x030D0000
  fp = tstate->current_frame;
#else
  _PyCFrame* cframe = tstate->cframe;
  if (cframe == NULL ||
      !safe_copy(&fp, &cframe->current_frame, sizeof(fp))) {
    return 0;
  }
#endif
  // The frame's fixed part (not its locals and stack).
  struct _PyInterpreterFrame f;
  if (!safe_copy(&f, fp, offsetof(struct _PyInterpreterFrame, localsplus))) {
    return 0;
  }
#if PY_VERSION_HEX >= 0x030E0000
  PyObject* executable = PyStackRef_AsPyObjectBorrow(f.f_executable);
  const _Py_CODEUNIT* ip = f.instr_ptr;
#elif PY_VERSION_HEX >= 0x030D0000
  PyObject* executable = f.f_executable;
  const _Py_CODEUNIT* ip = f.instr_ptr;
#else
  PyObject* executable = (PyObject*)f.f_code;
  const _Py_CODEUNIT* ip = f.prev_instr;  // the instruction started last
#endif
  if (!is_code(executable) || ip == NULL) return 0;
  PyCodeObject* code = (PyCodeObject*)executable;
  // Address arithmetic only: co_code_adaptive is inline in the object.
  const _Py_CODEUNIT* start = _PyCode_CODE(code);
  if (ip < start) return 0;
  *code_out = (uintptr_t)code;
  *offset_out = (int)((ip - start) * (Py_ssize_t)sizeof(_Py_CODEUNIT));
  return 1;
#else
  // Before 3.11 frames are objects, and tstate->frame is set only once the
  // new one is complete.
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
}

// On Windows another thread reads the (suspended) main thread's frame, so
// a fault reading it means only that the location is unknown.
static int scalene_peek_frame(PyThreadState* tstate, uintptr_t* code_out,
                              int* offset_out) {
#if defined(_MSC_VER)
  __try {
    return peek_frame(tstate, code_out, offset_out);
  } __except (EXCEPTION_EXECUTE_HANDLER) {
    return 0;
  }
#else
  return peek_frame(tstate, code_out, offset_out);
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
