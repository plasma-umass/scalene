#include "pywhere.hpp"
#include "traceconfig.hpp"

#include <Python.h>
#include <dlfcn.h>
#include <frameobject.h>

#include <mutex>
#include <vector>
#include <unordered_map>

#include <unistd.h>


// NOTE: uncomment for debugging, but this causes issues
// for production builds on Alpine
//
// #include "printf.h"
const int NEWLINE_TRIGGER_LENGTH = 98820;

static bool last_profiled_invalidated = false;
// An RAII class to simplify acquiring and releasing the GIL.
class GIL {
 public:
  GIL() { _gstate = PyGILState_Ensure(); }
  ~GIL() { PyGILState_Release(_gstate); }

 private:
  PyGILState_STATE _gstate;
};

#include "pyptr.h"

#if PY_VERSION_HEX < 0x03090000  // new in 3.9
inline PyFrameObject* PyThreadState_GetFrame(PyThreadState* threadState) {
  if (threadState != nullptr && threadState->frame != nullptr &&
      // threadState->frame is a "borrowed" reference.  With Python 3.8.10,
      // this sometimes refers to a zero-refcount frame that, if we were to
      // attempt freeing again (when we decrement back to 0), glibc would
      // abort due to a double free.
      threadState->frame->ob_base.ob_base.ob_refcnt > 0) {
    Py_XINCREF(threadState->frame);
    return threadState->frame;
  }
  return nullptr;
}
inline PyCodeObject* PyFrame_GetCode(PyFrameObject* frame) {
  Py_XINCREF(frame->f_code);
  return frame->f_code;
}
inline PyFrameObject* PyFrame_GetBack(PyFrameObject* frame) {
  Py_XINCREF(frame->f_back);
  return frame->f_back;
}
#endif
#if PY_VERSION_HEX < 0x030B0000  // new in 3.11
inline int PyFrame_GetLasti(PyFrameObject* frame) { return frame->f_lasti; }
#endif

#if PY_VERSION_HEX >= 0x030B0000
typedef struct _frame {
    PyObject_HEAD
    PyFrameObject *f_back;      /* previous frame, or NULL */
    void *f_frame; /* points to the frame data */
    PyObject *f_trace;          /* Trace function */
    int f_lineno;               /* Current line number. Only valid if non-zero */
    char f_trace_lines;         /* Emit per-line trace events? */
    char f_trace_opcodes;       /* Emit per-opcode trace events? */
    char f_fast_as_locals;      /* Have the fast locals of this frame been converted to a dict? */
    /* The frame data, if this frame object owns the frame */
    PyObject *_f_frame_data[1];
} PyFrameType;
#else
typedef  PyFrameObject PyFrameType;
#endif

static PyPtr<PyFrameObject> findMainPythonThread_frame() {
  PyThreadState* main = nullptr;

  PyThreadState* t = PyInterpreterState_ThreadHead(PyInterpreterState_Main());
  for (; t != nullptr; t = PyThreadState_Next(t)) {
    // Recognize the main thread as the one with the smallest ID.
    // In Juan's experiments, it's the last thread on the list and has id 1.
    //
    // FIXME this could be brittle...  another way would be to use
    // _PyRuntime.main_thread (a native thread ID) and compare it to
    // PyThreadState.thread_id, with the caveats that main_thread, etc.
    // might go away or change, and thread_id is initialized with the
    // native thread ID of whichever thread creates that PyThreadState.
    if (main == nullptr || main->id > t->id) {
      main = t;
    }
  }

  return PyPtr<PyFrameObject>(main ? PyThreadState_GetFrame(main) : nullptr);
}
// I'm not sure whether last_profiled_invalidated is quite needed, so I'm leaving this infrastructure here
//
PyObject* get_last_profiled_invalidated(PyObject* self, PyObject* args) {
  if (last_profiled_invalidated) {
    Py_RETURN_TRUE;
  }
  Py_RETURN_FALSE;
}

PyObject* set_last_profiled_invalidated_true(PyObject* self, PyObject* args) {
  last_profiled_invalidated = true;
  Py_RETURN_NONE;
}

PyObject* set_last_profiled_invalidated_false(PyObject* self, PyObject* args) {
  last_profiled_invalidated = false;
  Py_RETURN_NONE;
}


PyObject* set_scalene_done_true(PyObject* self, PyObject* args) {
    auto scalene_done =
      (std::atomic_bool*)dlsym(RTLD_DEFAULT, "p_scalene_done");
    if (scalene_done == nullptr) {
      PyErr_SetString(PyExc_Exception, "Unable to find p_scalene_done");
      return NULL;
    }
  *scalene_done = true;
  Py_RETURN_NONE;
}
PyObject* set_scalene_done_false(PyObject* self, PyObject* args) {
    auto scalene_done =
      (std::atomic_bool*)dlsym(RTLD_DEFAULT, "p_scalene_done");
    if (scalene_done == nullptr) {
      PyErr_SetString(PyExc_Exception, "Unable to find p_whereInPython");
      return NULL;
    }
  *scalene_done = false;
  Py_RETURN_NONE;
}

int whereInPython(std::string& filename, int& lineno, int& bytei) {
  if (!Py_IsInitialized()) {  // No python, no python stack.
    return 0;
  }
  // This function walks the Python stack until it finds a frame
  // corresponding to a file we are actually profiling. On success,
  // it updates filename, lineno, and byte code index appropriately,
  // and returns 1.  If the stack walk encounters no such file, it
  // sets the filename to the pseudo-filename "<BOGUS>" for special
  // treatment within Scalene, and returns 0.
  filename = "<BOGUS>";
  lineno = 1;
  bytei = 0;
  GIL gil;

  PyThreadState* threadState = PyGILState_GetThisThreadState();
  PyPtr<PyFrameObject> frame =
      threadState ? PyThreadState_GetFrame(threadState) : nullptr;

  if (static_cast<PyFrameObject*>(frame) == nullptr) {
    // Various packages may create native threads; attribute what they do
    // to what the main thread is doing, as it's likely to have requested it.
    frame = findMainPythonThread_frame();  // note this may be nullptr
  }

  auto traceConfig = TraceConfig::getInstance();
  if (!traceConfig) {
    return 0;
  }

  while (static_cast<PyFrameObject*>(frame) != nullptr) {
    PyPtr<PyCodeObject> code =
        PyFrame_GetCode(static_cast<PyFrameObject*>(frame));
    PyPtr<> co_filename =
        PyUnicode_AsASCIIString(static_cast<PyCodeObject*>(code)->co_filename);
    
    if (!(static_cast<PyObject*>(co_filename))) {
      return 0;
    }

    auto filenameStr = PyBytes_AsString(static_cast<PyObject*>(co_filename));
    if (filenameStr == NULL || strlen(filenameStr) == 0) {
      continue;
    }

    if (traceConfig->should_trace(filenameStr)) {

#if defined(PyPy_FatalError)
      // If this macro is defined, we are compiling PyPy, which
      // AFAICT does not have any way to access bytecode index, so
      // we punt and set it to 0.
      bytei = 0;
#else
      bytei = PyFrame_GetLasti(static_cast<PyFrameObject*>(frame));
#endif
      lineno = PyFrame_GetLineNumber(static_cast<PyFrameObject*>(frame));
      
      filename = filenameStr;
      return 1;
    }

    frame = PyFrame_GetBack(static_cast<PyFrameObject*>(frame));
  }
  return 0;
}

static PyObject* register_files_to_profile(PyObject* self, PyObject* args) {
  PyObject* a_list;
  PyObject* base_path;
  int profile_all;
  if (!PyArg_ParseTuple(args, "OOp", &a_list, &base_path, &profile_all))
    return NULL;
  auto is_list = PyList_Check(a_list);
  if (!is_list) {
    PyErr_SetString(PyExc_Exception, "Requires list or list-like object");
    return NULL;
  }
  TraceConfig::setInstance(new TraceConfig(a_list, base_path, profile_all));

  auto p_where =
      (decltype(p_whereInPython)*)dlsym(RTLD_DEFAULT, "p_whereInPython");
  if (p_where == nullptr) {
    PyErr_SetString(PyExc_Exception, "Unable to find p_whereInPython");
    return NULL;
  }
  *p_where = whereInPython;


  Py_RETURN_NONE;
}

static PyObject* print_files_to_profile(PyObject* self, PyObject* args) {
  if (TraceConfig* pl = TraceConfig::getInstance()) {
    pl->print();
  }
  Py_RETURN_NONE;
}
typedef struct {
  PyObject* scalene_module;
  PyObject* scalene_dict;
  PyObject* scalene_profiler_module;
  PyObject* scalene_class;
  PyObject* scalene_class_dict;
  PyObject* scalene_last_profiled;
  PyObject* invalidate_queue;
  PyObject* nada;
  PyObject* zero;
} unchanging_modules;

static unchanging_modules module_pointers;


static bool on_stack(char* outer_filename, int lineno, PyFrameObject* frame) {
  while(frame != NULL) {
    int iter_lineno = PyFrame_GetLineNumber(frame);
    

    PyPtr<PyCodeObject> code =
          PyFrame_GetCode(static_cast<PyFrameObject*>(frame));

    PyPtr<> co_filename(PyUnicode_AsASCIIString(static_cast<PyCodeObject*>(code)->co_filename));
    auto fname = PyBytes_AsString(static_cast<PyObject*>(co_filename));
    if (iter_lineno == lineno && strstr(fname, outer_filename)) {
      Py_XDECREF(frame);
      return true;
    }
    Py_XDECREF(frame);
    frame = PyFrame_GetBack(frame);
  }
  return false;
}

static void allocate_newline() {
  PyPtr<> abc(PyLong_FromLong(NEWLINE_TRIGGER_LENGTH));
  PyPtr<> tmp(PyByteArray_FromObject(static_cast<PyObject*>(abc)));

}

static int trace_func(PyObject* obj, PyFrameObject* frame, int what, PyObject* arg) {
  if (what != PyTrace_LINE) {
    return 0;
  }
  auto cast_frame = static_cast<PyFrameType*>(frame);
  int lineno = PyFrame_GetLineNumber(frame);

  PyPtr<PyCodeObject> code(PyFrame_GetCode(static_cast<PyFrameObject*>(frame)));
  // Take ownership of these right now
  PyObject* last_fname(PyList_GetItem(static_cast<PyObject*>(module_pointers.scalene_last_profiled), 0));
  Py_IncRef(last_fname);
  PyObject* last_lineno(PyList_GetItem(static_cast<PyObject*>(module_pointers.scalene_last_profiled), 1));
  Py_IncRef(last_lineno);
  auto lineno_l = PyLong_AsLong(static_cast<PyObject*>(last_lineno));
  if (lineno == lineno_l && PyUnicode_Compare(static_cast<PyObject*>(last_fname), static_cast<PyCodeObject*>(code)->co_filename) == 0) {
    return 0;
  }
  PyPtr<> last_fname_unicode( PyUnicode_AsASCIIString(last_fname));
  auto last_fname_s = PyBytes_AsString(static_cast<PyObject*>(last_fname_unicode));
    PyPtr<> co_filename(PyUnicode_AsASCIIString(static_cast<PyCodeObject*>(code)->co_filename));

  // Needed because decref will be called in on_stack
  Py_INCREF(frame);
  if (on_stack(last_fname_s, lineno_l, static_cast<PyFrameObject*>(frame))) {
    frame->f_trace_lines = 0;
    return 0;
  }

  PyEval_SetTrace(NULL, NULL);
  Py_IncRef(module_pointers.nada);
  auto res = PyList_SetItem(module_pointers.scalene_last_profiled, 0, module_pointers.nada);
  Py_IncRef(module_pointers.zero);
  res = PyList_SetItem(module_pointers.scalene_last_profiled, 1,  module_pointers.zero);

  PyObject* last_profiled_ret(PyTuple_Pack(2, last_fname,last_lineno ));
  Py_IncRef(module_pointers.zero);
  res = PyList_SetItem(module_pointers.scalene_last_profiled, 2, module_pointers.zero);

  allocate_newline();
  last_profiled_invalidated = true;
  Py_IncRef(last_profiled_ret);
  
  res = PyList_Append(module_pointers.invalidate_queue, last_profiled_ret);

  
  return 0;
}

static PyObject* populate_struct(PyObject* self, PyObject* args) {
  PyObject* scalene_module(PyImport_GetModule(PyUnicode_FromString("scalene"))); // New reference
  PyObject* scalene_dict(PyModule_GetDict(static_cast<PyObject*>(scalene_module)));
  Py_IncRef(scalene_dict);
  PyObject* scalene_profiler_module(PyDict_GetItemString(scalene_dict, "scalene_profiler"));
  Py_IncRef(scalene_profiler_module);
  PyObject* scalene_class(PyDict_GetItemString(PyModule_GetDict(scalene_profiler_module), "Scalene"));
  Py_IncRef(scalene_class);
  PyObject* scalene_class_dict(PyObject_GenericGetDict(scalene_class, NULL));
  PyObject* last_profiled(PyObject_GetAttrString(scalene_class, "_Scalene__last_profiled"));
  PyObject* invalidate_queue(PyObject_GetAttrString(scalene_class, "_Scalene__invalidate_queue"));
  PyObject* zero(PyLong_FromSize_t(0));
  PyObject* nada(PyUnicode_FromString("NADA"));
  module_pointers = {
    scalene_module,
    scalene_dict,
    scalene_profiler_module,
    scalene_class,
    scalene_class_dict,
    last_profiled, 
    invalidate_queue,
    nada,
    zero
  };
  Py_RETURN_NONE;
}

static PyObject* depopulate_struct(PyObject* self, PyObject* args) {
  auto m = module_pointers;
  Py_DECREF(m.scalene_module);
  Py_DECREF(m.scalene_dict);
  Py_DECREF(m.scalene_profiler_module);
  Py_DECREF(m.scalene_class);
  Py_DECREF(m.scalene_class_dict);
  Py_DECREF(m.scalene_last_profiled);
  Py_DECREF(m.invalidate_queue);
  Py_DECREF(m.nada);
  Py_DECREF(m.zero);
  module_pointers = {};
  Py_RETURN_NONE;
}

static PyObject* enable_settrace(PyObject* self, PyObject* args) {
  PyEval_SetTrace(trace_func, NULL);
  Py_RETURN_NONE;
}

static PyObject* disable_settrace(PyObject* self, PyObject* args) {
  PyEval_SetTrace(NULL, NULL);
  Py_RETURN_NONE;
}

// static PyObject* return_buffer(PyObject* self, PyObject* args) {
//   return PyByteArray_FromObject(PyLong_FromLong(50));
// }

static PyMethodDef EmbMethods[] = {
    {"register_files_to_profile", register_files_to_profile, METH_VARARGS,
     "Provides list of things into allocator"},
    {"print_files_to_profile", print_files_to_profile, METH_NOARGS,
     "printing for debug"},
    //  {"return_buffer", return_buffer, METH_NOARGS, ""},
    {"enable_settrace", enable_settrace, METH_NOARGS, ""},
    {"disable_settrace", disable_settrace, METH_NOARGS, ""},
    {"populate_struct", populate_struct, METH_NOARGS, ""},
    {"depopulate_struct", depopulate_struct, METH_NOARGS, ""},
    {"get_last_profiled_invalidated", get_last_profiled_invalidated, METH_NOARGS, ""},
    {"set_last_profiled_invalidated_true", set_last_profiled_invalidated_true, METH_NOARGS, ""},
    {"set_last_profiled_invalidated_false", set_last_profiled_invalidated_false, METH_NOARGS, ""},
    {"set_scalene_done_true", set_scalene_done_true, METH_NOARGS, ""},
    {"set_scalene_done_false", set_scalene_done_false, METH_NOARGS, ""},


    {NULL, NULL, 0, NULL}};

static PyModuleDef EmbedModule = {PyModuleDef_HEAD_INIT,
                                  "pywhere",
                                  NULL,
                                  -1,
                                  EmbMethods,
                                  NULL,
                                  NULL,
                                  NULL,
                                  NULL};

PyMODINIT_FUNC PyInit_pywhere() { return PyModule_Create(&EmbedModule); }
