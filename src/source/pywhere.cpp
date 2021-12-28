#include "pywhere.hpp"

#include <Python.h>
#include <dlfcn.h>
#include <frameobject.h>

#include <mutex>
#include <vector>

#include "printf.h"

class TraceConfig {
 public:
  TraceConfig(PyObject* list_wrapper, PyObject* base_path, bool profile_all_b) {
    // Assumes that each item is a bytes object
    owner = list_wrapper;
    path_owner = base_path;
    Py_INCREF(owner);
    Py_INCREF(path_owner);
    profile_all = profile_all_b;
    auto size = PyList_Size(owner);
    items.reserve(size);
    for (int i = 0; i < size; i++) {
      auto item = PyList_GetItem(owner, i);

      items.push_back(PyBytes_AsString(PyUnicode_AsASCIIString(item)));
    }
    scalene_base_path = PyBytes_AsString(PyUnicode_AsASCIIString(base_path));
  }

  bool should_trace(char* filename) {
    if (strstr(filename, "site-packages") || strstr(filename, "/lib/python")) {
      return false;
    }

    if (*filename == '<' && strstr(filename, "<ipython")) {
      return true;
    }

    if (strstr(filename, "scalene/scalene")) {
      return false;
    }

    if (owner != nullptr) {
      for (char* traceable : items) {
        if (strstr(filename, traceable)) {
          return true;
        }
      }
    }

    char resolved_path[PATH_MAX];
    if (!realpath(filename, resolved_path)) {
      fprintf(stderr, "Error getting real path: %d\n", errno);
      abort();
    }

    return strstr(resolved_path, scalene_base_path) != nullptr;
  }

  void print() {
    printf("Profile all? %d\nitems {", profile_all);
    for (auto c : items) {
      printf("\t%s\n", c);
    }
    printf("}\n");
  }

  static void setInstance(TraceConfig* instance) {
    std::lock_guard<decltype(_instanceMutex)> g(_instanceMutex);
    delete _instance;
    _instance = instance;
  }

  static TraceConfig* getInstance() {
    std::lock_guard<decltype(_instanceMutex)> g(_instanceMutex);
    return _instance;
  }

 private:
  std::vector<char*> items;
  char* scalene_base_path;
  // This is to keep the object in scope so that
  // the data pointers are always valid
  PyObject* owner;
  PyObject* path_owner;
  bool profile_all;

  static std::mutex _instanceMutex;
  static TraceConfig* _instance;
};

TraceConfig* TraceConfig::_instance = 0;
std::mutex TraceConfig::_instanceMutex;

// An RAII class to simplify acquiring and releasing the GIL.
class GIL {
 public:
  GIL() { _gstate = PyGILState_Ensure(); }
  ~GIL() { PyGILState_Release(_gstate); }

 private:
  PyGILState_STATE _gstate;
};

// Implements a mini smart pointer to PyObject.
// Manages a "strong" reference to the object... to use with a weak reference,
// Py_IncRef it first. Unfortunately, not all PyObject subclasses (e.g.,
// PyFrameObject) are declared as such, so we need to make this a template and
// cast.
template <class O = PyObject>
class PyPtr {
 public:
  PyPtr(O* o) : _obj(o) {}

  O* operator->() { return _obj; }

  operator O*() { return _obj; }

  PyPtr& operator=(O* o) {
    Py_DecRef((PyObject*)_obj);
    _obj = o;
    return *this;
  }

  PyPtr& operator=(PyPtr& ptr) {
    Py_IncRef((PyObject*)ptr._obj);
    *this = ptr._obj;
    return *this;
  }

  ~PyPtr() { Py_DecRef((PyObject*)_obj); }

 private:
  O* _obj;
};

static PyThreadState* findMainPythonThread() {
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

  return main;
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
  if (threadState == 0 || threadState->frame == 0) {
    // Various packages may create native threads; attribute what they do
    // to what the main thread is doing, as it's likely to have requested it.
    threadState = findMainPythonThread();
    if (threadState == 0) {
      return 0;  // No thread, no stack
    }
  }

  auto traceConfig = TraceConfig::getInstance();
  if (!traceConfig) {
    return 0;
  }

  for (auto frame = threadState->frame; frame != nullptr;
       frame = frame->f_back) {
    auto fname = frame->f_code->co_filename;
    PyPtr<> encoded = PyUnicode_AsASCIIString(fname);
    if (!encoded) {
      return 0;
    }

    auto filenameStr = PyBytes_AsString(encoded);
    if (strlen(filenameStr) == 0) {
      continue;
    }

    if (!strstr(filenameStr, "<") && !strstr(filenameStr, "/python") &&
        !strstr(filenameStr, "scalene/scalene")) {
      if (traceConfig->should_trace(filenameStr)) {
#if defined(PyPy_FatalError)
        // If this macro is defined, we are compiling PyPy, which
        // AFAICT does not have any way to access bytecode index, so
        // we punt and set it to 0.
        bytei = 0;
#else
        bytei = frame->f_lasti;
#endif
        lineno = PyCode_Addr2Line(frame->f_code, bytei);

        filename = filenameStr;
        // printf_("FOUND IT: %s %d\n", filenameStr, lineno);
        return 1;
      }
    }
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

static PyMethodDef EmbMethods[] = {
    {"register_files_to_profile", register_files_to_profile, METH_VARARGS,
     "Provides list of things into allocator"},
    {"print_files_to_profile", print_files_to_profile, METH_NOARGS,
     "printing for debug"},
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
