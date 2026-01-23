#include "pywhere.hpp"

#include <Python.h>
#include <frameobject.h>

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <process.h>
#define getpid _getpid

// Windows: get pointer via accessor function since C++ symbols are mangled
static void* win_dlsym(const char* symbol) {
  HMODULE hModule = GetModuleHandleA("libscalene.dll");
  if (!hModule) {
    // Fallback to main module
    hModule = GetModuleHandle(NULL);
  }

  // For p_whereInPython and p_scalene_done, use accessor functions
  if (strcmp(symbol, "p_whereInPython") == 0) {
    typedef void* (*GetterFunc)();
    GetterFunc getter = (GetterFunc)GetProcAddress(hModule, "get_p_whereInPython");
    if (getter) return getter();
  }
  if (strcmp(symbol, "p_scalene_done") == 0) {
    typedef void* (*GetterFunc)();
    GetterFunc getter = (GetterFunc)GetProcAddress(hModule, "get_p_scalene_done");
    if (getter) return getter();
  }

  // Try direct lookup (for non-mangled symbols)
  void* addr = GetProcAddress(hModule, symbol);
  if (addr) return addr;

  return nullptr;
}
#define dlsym(handle, sym) win_dlsym(sym)
#define RTLD_DEFAULT nullptr
#else
#include <dlfcn.h>
#include <unistd.h>
#endif

#include <mutex>
#include <unordered_map>
#include <vector>

#include "traceconfig.hpp"

// NOTE: uncomment for debugging, but this causes issues
// for production builds on Alpine
//
// #include "printf.h"
const int NEWLINE_TRIGGER_LENGTH = 98820;

static bool last_profiled_invalidated = false;

// sys.monitoring support for Python 3.13+
#if PY_VERSION_HEX >= 0x030D0000
// Tool ID for sys.monitoring (PROFILER_ID = 2)
static const int SCALENE_TOOL_ID = 2;

// Whether sys.monitoring tracing is currently active
static bool sysmon_tracing_active = false;

// Call depth tracking to avoid on_stack check
// When we enable tracing, we record the call depth
// When we see a LINE event at the same or lower depth, we know we've moved to a new line
static int sysmon_initial_call_depth = 0;
static int sysmon_current_call_depth = 0;

// Cached sys.monitoring.DISABLE constant
static PyObject* sysmon_DISABLE = nullptr;
#endif
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
  PyObject_HEAD PyFrameObject* f_back; /* previous frame, or NULL */
  void* f_frame;                       /* points to the frame data */
  PyObject* f_trace;                   /* Trace function */
  int f_lineno;          /* Current line number. Only valid if non-zero */
  char f_trace_lines;    /* Emit per-line trace events? */
  char f_trace_opcodes;  /* Emit per-opcode trace events? */
  char f_fast_as_locals; /* Have the fast locals of this frame been converted to
                            a dict? */
  /* The frame data, if this frame object owns the frame */
  PyObject* _f_frame_data[1];
} PyFrameType;
#else
typedef PyFrameObject PyFrameType;
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
// I'm not sure whether last_profiled_invalidated is quite needed, so I'm
// leaving this infrastructure here
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
  auto scalene_done = (std::atomic_bool*)dlsym(RTLD_DEFAULT, "p_scalene_done");
  if (scalene_done == nullptr) {
    PyErr_SetString(PyExc_Exception, "Unable to find p_scalene_done");
    return NULL;
  }
  *scalene_done = true;
  Py_RETURN_NONE;
}
PyObject* set_scalene_done_false(PyObject* self, PyObject* args) {
  auto scalene_done = (std::atomic_bool*)dlsym(RTLD_DEFAULT, "p_scalene_done");
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

// Collect frames from all threads for CPU profiling.
// Returns a list of (thread_id, orig_frame) tuples - one per thread.
// Main thread is placed first in the list.
// NOTE: Does NOT filter frames - caller must apply should_trace filtering.
static PyObject* collect_frames_to_record(PyObject* self, PyObject* args) {
  if (!Py_IsInitialized()) {
    return PyList_New(0);  // Return empty list if Python not initialized
  }

  // Collect all thread states first
  std::vector<std::pair<PyThreadState*, unsigned long>> thread_states;
  PyThreadState* main_thread = nullptr;
  unsigned long main_thread_id = 0;

  PyInterpreterState* interp = PyInterpreterState_Main();
  if (!interp) {
    return PyList_New(0);
  }

  // Find main thread (smallest ID) and collect all threads
  for (PyThreadState* t = PyInterpreterState_ThreadHead(interp);
       t != nullptr;
       t = PyThreadState_Next(t)) {
    unsigned long tid = t->thread_id;
    thread_states.push_back({t, tid});
    if (main_thread == nullptr || main_thread->id > t->id) {
      main_thread = t;
      main_thread_id = tid;
    }
  }

  // Create result list
  PyObject* result = PyList_New(0);
  if (!result) {
    return nullptr;
  }

  // Helper lambda to add a thread's frame to result
  auto add_thread_frame = [&](PyThreadState* tstate, unsigned long tid) {
    PyPtr<PyFrameObject> frame = PyThreadState_GetFrame(tstate);
    if (!static_cast<PyFrameObject*>(frame)) {
      return;  // No frame for this thread
    }

    // Create tuple (thread_id, frame)
    PyObject* tuple = PyTuple_New(2);
    if (tuple) {
      PyTuple_SET_ITEM(tuple, 0, PyLong_FromUnsignedLong(tid));
      Py_INCREF(static_cast<PyFrameObject*>(frame));
      PyTuple_SET_ITEM(tuple, 1, reinterpret_cast<PyObject*>(
          static_cast<PyFrameObject*>(frame)));
      PyList_Append(result, tuple);
      Py_DECREF(tuple);
    }
  };

  // Process main thread first
  if (main_thread) {
    add_thread_frame(main_thread, main_thread_id);
  }

  // Process other threads
  for (size_t i = 0; i < thread_states.size(); i++) {
    PyThreadState* tstate = thread_states[i].first;
    unsigned long tid = thread_states[i].second;
    if (tstate != main_thread) {
      add_thread_frame(tstate, tid);
    }
  }

  return result;
}

// Set up TraceConfig only (doesn't require libscalene)
// Used for CPU-only profiling where we need TraceConfig for frame filtering
static PyObject* setup_trace_config(PyObject* self, PyObject* args) {
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
  Py_RETURN_NONE;
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
  while (frame != NULL) {
    int iter_lineno = PyFrame_GetLineNumber(frame);

    PyPtr<PyCodeObject> code =
        PyFrame_GetCode(static_cast<PyFrameObject*>(frame));

    PyPtr<> co_filename(
        PyUnicode_AsASCIIString(static_cast<PyCodeObject*>(code)->co_filename));
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

// sys.monitoring implementation for Python 3.13+
#if PY_VERSION_HEX >= 0x030D0000

// Get current call depth by walking the stack
static int get_call_depth() {
  int depth = 0;
  PyThreadState* tstate = PyThreadState_Get();
  if (tstate == nullptr) return 0;

  PyPtr<PyFrameObject> frame(PyThreadState_GetFrame(tstate));
  while (static_cast<PyFrameObject*>(frame) != nullptr) {
    depth++;
    frame = PyFrame_GetBack(static_cast<PyFrameObject*>(frame));
  }
  return depth;
}

// Finalize the current line for sys.monitoring
static void sysmon_finalize_line() {
  sysmon_tracing_active = false;

  // Get the last profiled location
  PyObject* last_fname = PyList_GetItem(module_pointers.scalene_last_profiled, 0);
  PyObject* last_lineno_obj = PyList_GetItem(module_pointers.scalene_last_profiled, 1);

  if (last_fname == nullptr || last_lineno_obj == nullptr) {
    return;
  }

  Py_INCREF(last_fname);
  Py_INCREF(last_lineno_obj);

  // Reset last profiled to sentinel values
  Py_INCREF(module_pointers.nada);
  PyList_SetItem(module_pointers.scalene_last_profiled, 0, module_pointers.nada);
  Py_INCREF(module_pointers.zero);
  PyList_SetItem(module_pointers.scalene_last_profiled, 1, module_pointers.zero);
  Py_INCREF(module_pointers.zero);
  PyList_SetItem(module_pointers.scalene_last_profiled, 2, module_pointers.zero);

  // Allocate the NEWLINE trigger
  allocate_newline();

  // Mark as invalidated
  last_profiled_invalidated = true;

  // Add to invalidate queue
  PyObject* tuple = PyTuple_Pack(2, last_fname, last_lineno_obj);
  if (tuple != nullptr) {
    PyList_Append(module_pointers.invalidate_queue, tuple);
    Py_DECREF(tuple);
  }

  Py_DECREF(last_fname);
  Py_DECREF(last_lineno_obj);

  // Disable LINE events
  PyObject* sys_module = PyImport_ImportModule("sys");
  if (sys_module) {
    PyObject* monitoring = PyObject_GetAttrString(sys_module, "monitoring");
    if (monitoring) {
      PyObject* set_events = PyObject_GetAttrString(monitoring, "set_events");
      if (set_events) {
        PyObject* args = Py_BuildValue("(ii)", SCALENE_TOOL_ID, 0);
        if (args) {
          PyObject* result = PyObject_CallObject(set_events, args);
          Py_XDECREF(result);
          Py_DECREF(args);
        }
        Py_DECREF(set_events);
      }
      Py_DECREF(monitoring);
    }
    Py_DECREF(sys_module);
  }
}

// Initialize the cached DISABLE constant
static void ensure_sysmon_disable_cached() {
  if (sysmon_DISABLE != nullptr) {
    return;
  }
  PyObject* sys_module = PyImport_ImportModule("sys");
  if (!sys_module) return;
  PyObject* monitoring = PyObject_GetAttrString(sys_module, "monitoring");
  Py_DECREF(sys_module);
  if (!monitoring) return;
  sysmon_DISABLE = PyObject_GetAttrString(monitoring, "DISABLE");
  Py_DECREF(monitoring);
  // Keep a reference to DISABLE for the lifetime of the module
}

// LINE event callback for sys.monitoring
// Returns: Py_None to continue, or sys.monitoring.DISABLE constant to disable
static PyObject* sysmon_line_callback(PyObject* self, PyObject* args) {
  PyObject* code_obj;
  int line_number;

  if (!PyArg_ParseTuple(args, "Oi", &code_obj, &line_number)) {
    return nullptr;
  }

  // Ensure we have the cached DISABLE constant
  ensure_sysmon_disable_cached();
  if (!sysmon_DISABLE) {
    Py_RETURN_NONE;
  }

  if (!sysmon_tracing_active) {
    Py_INCREF(sysmon_DISABLE);
    return sysmon_DISABLE;
  }

  // Get the last profiled location
  PyObject* last_fname = PyList_GetItem(module_pointers.scalene_last_profiled, 0);
  PyObject* last_lineno_obj = PyList_GetItem(module_pointers.scalene_last_profiled, 1);

  if (last_fname == nullptr || last_lineno_obj == nullptr) {
    Py_INCREF(sysmon_DISABLE);
    return sysmon_DISABLE;
  }

  long last_lineno = PyLong_AsLong(last_lineno_obj);

  // Get current filename from code object
  PyCodeObject* code = (PyCodeObject*)code_obj;
  PyObject* current_fname = code->co_filename;

  // Check if we're still on the same line
  if (line_number == last_lineno &&
      PyUnicode_Compare(current_fname, last_fname) == 0) {
    // Still on the same line, keep tracing
    Py_RETURN_NONE;
  }

  // We've moved to a different line.
  // Use call depth tracking instead of on_stack check.
  // If current call depth is greater than initial, we're inside a function call
  // from the original line, so don't finalize yet.
  int current_depth = get_call_depth();
  if (current_depth > sysmon_initial_call_depth) {
    // We're inside a call from the original line
    Py_RETURN_NONE;
  }

  // We've moved to a genuinely different line - finalize the previous line
  sysmon_finalize_line();

  Py_INCREF(sysmon_DISABLE);
  return sysmon_DISABLE;
}

// CALL event callback for sys.monitoring - tracks call depth
static PyObject* sysmon_call_callback(PyObject* self, PyObject* args) {
  // Increment call depth when entering a function
  sysmon_current_call_depth++;
  Py_RETURN_NONE;
}

// PY_RETURN event callback for sys.monitoring - tracks call depth
static PyObject* sysmon_return_callback(PyObject* self, PyObject* args) {
  // Decrement call depth when returning from a function
  if (sysmon_current_call_depth > 0) {
    sysmon_current_call_depth--;
  }

  // If we've returned to or below the initial depth, check if we should finalize
  if (sysmon_tracing_active && sysmon_current_call_depth <= sysmon_initial_call_depth) {
    // We've returned from the call that was made from the profiled line
    // The next LINE event will handle finalization
  }

  Py_RETURN_NONE;
}

// Enable sys.monitoring tracing
static PyObject* enable_sysmon(PyObject* self, PyObject* args) {
  sysmon_tracing_active = true;
  sysmon_initial_call_depth = get_call_depth();
  sysmon_current_call_depth = sysmon_initial_call_depth;

  // Enable LINE events via sys.monitoring.set_events
  PyObject* sys_module = PyImport_ImportModule("sys");
  if (!sys_module) {
    PyErr_SetString(PyExc_RuntimeError, "Cannot import sys");
    return nullptr;
  }

  PyObject* monitoring = PyObject_GetAttrString(sys_module, "monitoring");
  Py_DECREF(sys_module);
  if (!monitoring) {
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring");
    return nullptr;
  }

  // Get events.LINE constant
  PyObject* events = PyObject_GetAttrString(monitoring, "events");
  if (!events) {
    Py_DECREF(monitoring);
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring.events");
    return nullptr;
  }

  PyObject* LINE = PyObject_GetAttrString(events, "LINE");
  Py_DECREF(events);
  if (!LINE) {
    Py_DECREF(monitoring);
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring.events.LINE");
    return nullptr;
  }

  // Call set_events(SCALENE_TOOL_ID, events.LINE)
  PyObject* set_events = PyObject_GetAttrString(monitoring, "set_events");
  if (!set_events) {
    Py_DECREF(LINE);
    Py_DECREF(monitoring);
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring.set_events");
    return nullptr;
  }

  long line_event = PyLong_AsLong(LINE);
  Py_DECREF(LINE);

  PyObject* result = PyObject_CallFunction(set_events, "ii", SCALENE_TOOL_ID, (int)line_event);
  Py_DECREF(set_events);
  Py_DECREF(monitoring);

  if (!result) {
    return nullptr;
  }
  Py_DECREF(result);

  Py_RETURN_NONE;
}

// Disable sys.monitoring tracing
static PyObject* disable_sysmon(PyObject* self, PyObject* args) {
  sysmon_tracing_active = false;

  // Disable all events via sys.monitoring.set_events(SCALENE_TOOL_ID, 0)
  PyObject* sys_module = PyImport_ImportModule("sys");
  if (!sys_module) {
    Py_RETURN_NONE;
  }

  PyObject* monitoring = PyObject_GetAttrString(sys_module, "monitoring");
  Py_DECREF(sys_module);
  if (!monitoring) {
    Py_RETURN_NONE;
  }

  PyObject* set_events = PyObject_GetAttrString(monitoring, "set_events");
  if (!set_events) {
    Py_DECREF(monitoring);
    Py_RETURN_NONE;
  }

  PyObject* result = PyObject_CallFunction(set_events, "ii", SCALENE_TOOL_ID, 0);
  Py_XDECREF(result);
  Py_DECREF(set_events);
  Py_DECREF(monitoring);

  Py_RETURN_NONE;
}

// Register the sys.monitoring callbacks
static PyObject* setup_sysmon(PyObject* self, PyObject* args) {
  PyObject* line_callback;

  if (!PyArg_ParseTuple(args, "O", &line_callback)) {
    return nullptr;
  }

  // Get sys.monitoring module
  PyObject* sys_module = PyImport_ImportModule("sys");
  if (!sys_module) {
    PyErr_SetString(PyExc_RuntimeError, "Cannot import sys");
    return nullptr;
  }

  PyObject* monitoring = PyObject_GetAttrString(sys_module, "monitoring");
  Py_DECREF(sys_module);
  if (!monitoring) {
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring");
    return nullptr;
  }

  // Try to use the tool ID
  PyObject* use_tool_id = PyObject_GetAttrString(monitoring, "use_tool_id");
  if (use_tool_id) {
    PyObject* result = PyObject_CallFunction(use_tool_id, "is", SCALENE_TOOL_ID, "scalene");
    // Ignore ValueError if tool ID is already in use
    if (!result && PyErr_ExceptionMatches(PyExc_ValueError)) {
      PyErr_Clear();
    } else {
      Py_XDECREF(result);
    }
    Py_DECREF(use_tool_id);
  }

  // Get events.LINE constant
  PyObject* events = PyObject_GetAttrString(monitoring, "events");
  if (!events) {
    Py_DECREF(monitoring);
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring.events");
    return nullptr;
  }

  PyObject* LINE = PyObject_GetAttrString(events, "LINE");
  Py_DECREF(events);
  if (!LINE) {
    Py_DECREF(monitoring);
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring.events.LINE");
    return nullptr;
  }

  // Register the LINE callback
  PyObject* register_callback = PyObject_GetAttrString(monitoring, "register_callback");
  if (!register_callback) {
    Py_DECREF(LINE);
    Py_DECREF(monitoring);
    PyErr_SetString(PyExc_RuntimeError, "Cannot access sys.monitoring.register_callback");
    return nullptr;
  }

  PyObject* result = PyObject_CallFunction(register_callback, "iOO", SCALENE_TOOL_ID, LINE, line_callback);
  Py_DECREF(register_callback);
  Py_DECREF(LINE);
  Py_DECREF(monitoring);

  if (!result) {
    return nullptr;
  }
  Py_DECREF(result);

  Py_RETURN_NONE;
}

// Check if sys.monitoring is available (Python 3.13+)
static PyObject* sysmon_available(PyObject* self, PyObject* args) {
  Py_RETURN_TRUE;
}

// Get the tool ID used by scalene
static PyObject* get_sysmon_tool_id(PyObject* self, PyObject* args) {
  return PyLong_FromLong(SCALENE_TOOL_ID);
}

// Check if sys.monitoring tracing is active
static PyObject* is_sysmon_active(PyObject* self, PyObject* args) {
  if (sysmon_tracing_active) {
    Py_RETURN_TRUE;
  }
  Py_RETURN_FALSE;
}

#else
// Stubs for Python < 3.13

static PyObject* enable_sysmon(PyObject* self, PyObject* args) {
  PyErr_SetString(PyExc_NotImplementedError, "sys.monitoring C API requires Python 3.13+");
  return nullptr;
}

static PyObject* disable_sysmon(PyObject* self, PyObject* args) {
  PyErr_SetString(PyExc_NotImplementedError, "sys.monitoring C API requires Python 3.13+");
  return nullptr;
}

static PyObject* setup_sysmon(PyObject* self, PyObject* args) {
  PyErr_SetString(PyExc_NotImplementedError, "sys.monitoring C API requires Python 3.13+");
  return nullptr;
}

static PyObject* sysmon_available(PyObject* self, PyObject* args) {
  Py_RETURN_FALSE;
}

static PyObject* get_sysmon_tool_id(PyObject* self, PyObject* args) {
  return PyLong_FromLong(2);  // PROFILER_ID
}

static PyObject* is_sysmon_active(PyObject* self, PyObject* args) {
  Py_RETURN_FALSE;
}

static PyObject* sysmon_line_callback(PyObject* self, PyObject* args) {
  PyErr_SetString(PyExc_NotImplementedError, "sys.monitoring C API requires Python 3.13+");
  return nullptr;
}

#endif  // PY_VERSION_HEX >= 0x030D0000

static int trace_func(PyObject* obj, PyFrameObject* frame, int what,
                      PyObject* arg) {
  if (what == PyTrace_CALL || what == PyTrace_C_CALL) {
    // Prior to this check, trace_func was called
    // in every child frame. When we figured out the frame
    // was a child of the current line, only then did we disable tracing in that frame. 
    // This was causing a major slowdown when importing pytorch-- from what we can tell,
    // the import itself called many functions and the call overhead of the entire tracing harness
    // was incurred for each call at least once.
    // 
    //
    // What we're trying to do here, though, is see if we have moved on to another line of the client program. 
    // Therefore, we can disable tracing for the moment, since one of three things has happened:
    //
    // 1. We have called a library function. We therefore know that there will be absolutely no important events coming from this
    //    frame, since the program can't progress to the next line before until the call has ended
    //
    // 2. We have called a client function. We know that the line we were on hasn't ended yet, since we would get a PyTrace_Line
    //    event if that did happen. This leaves us with one of two cases:
    //    
    //    2.1: The function makes no allocations. Therefore, not tracing Line events in its frame is valid and the next Line
    //         we get is in the parent frame, the one that we care about
    //    2.2: the function does make an allocation. In that case, we separately enable settrace at that allocation,
    //         so we still track it
    //
    //
    // FIXME: if, in a single line, we see a pattern in a single line like allocation -> client call w/ allocation, we won't actually increment
    //        the n_mallocs counter for the line we started with
    frame->f_trace_lines = 0;
    frame->f_trace = NULL;
    #if PY_VERSION_HEX >= 0x030a0000 && PY_VERSION_HEX < 0x030c0000 
    // This pre-3.12 optimization only exists post 3.9
    PyThreadState* tstate = PyThreadState_Get();
    tstate->cframe->use_tracing = 0;
    #endif
   
  }
  if (what != PyTrace_LINE) {
    return 0;
  }
  auto cast_frame = static_cast<PyFrameType*>(frame);
  int lineno = PyFrame_GetLineNumber(frame);

  PyPtr<PyCodeObject> code(PyFrame_GetCode(static_cast<PyFrameObject*>(frame)));
  // Take ownership of these right now
  PyObject* last_fname(PyList_GetItem(
      static_cast<PyObject*>(module_pointers.scalene_last_profiled), 0));
  Py_IncRef(last_fname);
  PyObject* last_lineno(PyList_GetItem(
      static_cast<PyObject*>(module_pointers.scalene_last_profiled), 1));
  Py_IncRef(last_lineno);
  auto lineno_l = PyLong_AsLong(static_cast<PyObject*>(last_lineno));
  if (lineno == lineno_l &&
      PyUnicode_Compare(static_cast<PyObject*>(last_fname),
                        static_cast<PyCodeObject*>(code)->co_filename) == 0) {
    return 0;
  }
  PyPtr<> last_fname_unicode(PyUnicode_AsASCIIString(last_fname));
  auto last_fname_s =
      PyBytes_AsString(static_cast<PyObject*>(last_fname_unicode));
  PyPtr<> co_filename(
      PyUnicode_AsASCIIString(static_cast<PyCodeObject*>(code)->co_filename));

  // Needed because decref will be called in on_stack
  Py_INCREF(frame);
  if (on_stack(last_fname_s, lineno_l, static_cast<PyFrameObject*>(frame))) {
    return 0;
  }

  PyEval_SetTrace(NULL, NULL);
  Py_IncRef(module_pointers.nada);
  auto res = PyList_SetItem(module_pointers.scalene_last_profiled, 0,
                            module_pointers.nada);
  Py_IncRef(module_pointers.zero);
  res = PyList_SetItem(module_pointers.scalene_last_profiled, 1,
                       module_pointers.zero);

  PyObject* last_profiled_ret(PyTuple_Pack(2, last_fname, last_lineno));
  Py_IncRef(module_pointers.zero);
  res = PyList_SetItem(module_pointers.scalene_last_profiled, 2,
                       module_pointers.zero);

  allocate_newline();
  last_profiled_invalidated = true;
  Py_IncRef(last_profiled_ret);

  res = PyList_Append(module_pointers.invalidate_queue, last_profiled_ret);

  return 0;
}

static PyObject* populate_struct(PyObject* self, PyObject* args) {
  PyObject* scalene_module(
      PyImport_GetModule(PyUnicode_FromString("scalene")));  // New reference
  PyObject* scalene_dict(
      PyModule_GetDict(static_cast<PyObject*>(scalene_module)));
  Py_IncRef(scalene_dict);
  PyObject* scalene_profiler_module(
      PyDict_GetItemString(scalene_dict, "scalene_profiler"));
  Py_IncRef(scalene_profiler_module);
  PyObject* scalene_class(PyDict_GetItemString(
      PyModule_GetDict(scalene_profiler_module), "Scalene"));
  Py_IncRef(scalene_class);
  PyObject* scalene_class_dict(PyObject_GenericGetDict(scalene_class, NULL));
  PyObject* last_profiled(
      PyObject_GetAttrString(scalene_class, "_Scalene__last_profiled"));
  PyObject* invalidate_queue(
      PyObject_GetAttrString(scalene_class, "_Scalene__invalidate_queue"));
  PyObject* zero(PyLong_FromSize_t(0));
  PyObject* nada(PyUnicode_FromString("NADA"));
  module_pointers = {scalene_module,
                     scalene_dict,
                     scalene_profiler_module,
                     scalene_class,
                     scalene_class_dict,
                     last_profiled,
                     invalidate_queue,
                     nada,
                     zero};
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
  PyObject* frame;
  if (!PyArg_ParseTuple(args, "O", &frame)) {
    return NULL;
  }
  PyFrameObject* frame_obj = (PyFrameObject*) frame;
  PyEval_SetTrace(trace_func, NULL);
  frame_obj->f_trace_lines = 1;
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
    {"setup_trace_config", setup_trace_config, METH_VARARGS,
     "Set up TraceConfig for frame filtering (doesn't require libscalene)"},
    {"register_files_to_profile", register_files_to_profile, METH_VARARGS,
     "Provides list of things into allocator"},
    {"print_files_to_profile", print_files_to_profile, METH_NOARGS,
     "printing for debug"},
    {"collect_frames_to_record", collect_frames_to_record, METH_NOARGS,
     "Collect frames from all threads for CPU profiling"},
    //  {"return_buffer", return_buffer, METH_NOARGS, ""},
    {"enable_settrace", enable_settrace, METH_VARARGS, ""},
    {"disable_settrace", disable_settrace, METH_NOARGS, ""},
    {"populate_struct", populate_struct, METH_NOARGS, ""},
    {"depopulate_struct", depopulate_struct, METH_NOARGS, ""},
    {"get_last_profiled_invalidated", get_last_profiled_invalidated,
     METH_NOARGS, ""},
    {"set_last_profiled_invalidated_true", set_last_profiled_invalidated_true,
     METH_NOARGS, ""},
    {"set_last_profiled_invalidated_false", set_last_profiled_invalidated_false,
     METH_NOARGS, ""},
    {"set_scalene_done_true", set_scalene_done_true, METH_NOARGS, ""},
    {"set_scalene_done_false", set_scalene_done_false, METH_NOARGS, ""},
    // sys.monitoring support (Python 3.13+)
    {"enable_sysmon", enable_sysmon, METH_NOARGS,
     "Enable sys.monitoring line tracing"},
    {"disable_sysmon", disable_sysmon, METH_NOARGS,
     "Disable sys.monitoring line tracing"},
    {"setup_sysmon", setup_sysmon, METH_VARARGS,
     "Set up sys.monitoring with a line callback"},
    {"sysmon_available", sysmon_available, METH_NOARGS,
     "Check if sys.monitoring C API is available (Python 3.13+)"},
    {"get_sysmon_tool_id", get_sysmon_tool_id, METH_NOARGS,
     "Get the sys.monitoring tool ID used by scalene"},
    {"is_sysmon_active", is_sysmon_active, METH_NOARGS,
     "Check if sys.monitoring tracing is currently active"},
    {"sysmon_line_callback", sysmon_line_callback, METH_VARARGS,
     "C implementation of the sys.monitoring LINE callback"},

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
