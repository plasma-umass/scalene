#include <Python.h>
#include <limits.h>
#include <stdlib.h>

#include <mutex>
#include <vector>

#include "printf.h"

class PyStringPtrList {
 public:
  PyStringPtrList(PyObject* list_wrapper, PyObject* base_path,
                  bool profile_all_b) {
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
    is_initialized = true;
  }
  PyStringPtrList() { is_initialized = false; }

  bool initialized() { return is_initialized; }
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

 private:
  std::vector<char*> items;
  char* scalene_base_path;
  // This is to keep the object in scope so that
  // the data pointers are always valid
  PyObject* owner;
  PyObject* path_owner;
  bool profile_all;
  bool is_initialized;
};

static std::mutex _mx;
static PyStringPtrList py_string_ptr_list;

static void set_py_string_ptr_list(PyObject* p, PyObject* base_path,
                                   bool trace_all) {
  std::lock_guard<decltype(_mx)> g(_mx);
  py_string_ptr_list = PyStringPtrList{p, base_path, trace_all};
}
